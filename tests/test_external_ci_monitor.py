"""The external monitor must page on missing, red, stale and unreadable CI."""
import contextlib
import datetime as dt
import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'scripts/external-ci-monitor.py'
SPEC = importlib.util.spec_from_file_location('external_ci_monitor', SCRIPT)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)
NOW = dt.datetime(2026, 9, 30, 10, tzinfo=dt.timezone.utc)


def run(conclusion='success', age=1):
    return {'conclusion': conclusion, 'updatedAt': (NOW-dt.timedelta(hours=age)).isoformat(),
            'headSha': 'a'*40, 'url': 'https://github.com/example/repo/actions/runs/7', 'databaseId': 7}


class HealthVerdicts(unittest.TestCase):
    def test_recent_success_is_healthy(self):
        self.assertEqual(monitor.assess(run(), NOW)['status'], 'healthy')

    def test_staleness_is_exactly_24_hours(self):
        self.assertEqual(monitor.assess(run(age=23.99), NOW)['status'], 'healthy')
        self.assertEqual(monitor.assess(run(age=24), NOW)['status'], 'stale')

    def test_non_success_and_missing_runs_alert(self):
        for result in ('failure', 'cancelled', 'timed_out', 'skipped', 'action_required'):
            with self.subTest(result=result):
                self.assertEqual(monitor.assess(run(result), NOW)['status'], 'red')
        self.assertEqual(monitor.assess(None, NOW)['status'], 'missing')

    def test_malformed_completed_run_cannot_be_green(self):
        for change in ({'updatedAt': None}, {'updatedAt': 'yesterday'}, {'updatedAt': '2026-09-30T10:00:00'},
                       {'updatedAt': '2026-10-01T10:00:00Z'}, {'conclusion': None},
                       {'headSha': None}, {'headSha': 'invalid'}, {'url': None},
                       {'url': 'https://github.com/example/repo/actions/runs/8'},
                       {'databaseId': None}, {'databaseId': True}, {'databaseId': 0}):
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                monitor.assess({**run(), **change}, NOW)


class GitHubReader(unittest.TestCase):
    def test_latest_query_ignores_in_progress_runs(self):
        with patch.object(monitor, 'gh_json', return_value=[run()]) as gh:
            self.assertEqual(monitor.fetch_run('example/repo')['databaseId'], 7)
        args = gh.call_args.args[0]
        self.assertEqual(args[args.index('--status')+1], 'completed')
        self.assertEqual(args[args.index('--branch')+1], 'main')
        self.assertEqual(args[args.index('--event')+1], 'push')

    def test_empty_or_malformed_response(self):
        with patch.object(monitor, 'gh_json', return_value=[]):
            self.assertIsNone(monitor.fetch_run('example/repo'))
        with patch.object(monitor, 'gh_json', return_value={}), self.assertRaises(ValueError):
            monitor.fetch_run('example/repo')

    def test_drill_requires_a_real_unsuccessful_completed_validate_run(self):
        raw = {'name':'validate', 'status':'completed', 'conclusion':'failure', 'id':7,
               'head_sha':'a'*40, 'html_url':run()['url'], 'updated_at':run()['updatedAt']}
        with patch.object(monitor, 'gh_json', return_value=raw):
            self.assertEqual(monitor.fetch_run('example/repo', 7)['conclusion'], 'failure')
        for change in ({'name':'install'}, {'status':'in_progress'}, {'conclusion':'success'}):
            with self.subTest(change=change), patch.object(monitor, 'gh_json', return_value={**raw,**change}), self.assertRaises(ValueError):
                monitor.fetch_run('example/repo', 7)

    def test_api_error_does_not_echo_sensitive_stderr(self):
        failed = subprocess.CompletedProcess(['gh'], 1, '', 'private response')
        with patch.object(monitor.subprocess, 'run', return_value=failed), self.assertRaises(RuntimeError) as error:
            monitor.gh_json(['run','list'])
        self.assertNotIn('private response', str(error.exception))

    def test_exit_contract_and_authentication_failure(self):
        for value, expected in ((run(),0), (run('failure'),1), (None,1),
                                ({**run(), 'headSha': None},2), ({**run(), 'url': None},2),
                                ({**run(), 'databaseId': None},2)):
            with self.subTest(expected=expected), patch.object(monitor,'fetch_run',return_value=value), contextlib.redirect_stdout(io.StringIO()) as output:
                # Wall clock is later than the fixed fixture; recent success needs a current date.
                if value is not None:
                    value['updatedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
                self.assertEqual(monitor.main([]), expected)
                result = json.loads(output.getvalue())
                self.assertIn('status', result)
                if expected == 2:
                    self.assertEqual(result['status'], 'monitor-error')
        for error in (OSError(), RuntimeError(), subprocess.TimeoutExpired('gh',45), ValueError()):
            with self.subTest(error=type(error)), patch.object(monitor,'fetch_run',side_effect=error), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(monitor.main([]),2)
                self.assertEqual(json.loads(output.getvalue())['status'],'monitor-error')



class QuietWhenCurrent(unittest.TestCase):
    """A quiet repository is not an outage: a green run on main's current head stays
    healthy past 24 hours, while a head CI never finished still goes stale."""

    def test_old_green_run_on_the_current_head_is_healthy(self):
        self.assertEqual(monitor.assess(run(age=30), NOW, main_sha='a'*40)['status'], 'healthy')

    def test_main_moved_past_the_old_green_run_is_stale(self):
        self.assertEqual(monitor.assess(run(age=30), NOW, main_sha='b'*40)['status'], 'stale')

    def test_red_stays_red_on_the_current_head(self):
        self.assertEqual(monitor.assess(run('failure', age=30), NOW, main_sha='a'*40)['status'], 'red')

    def test_main_head_must_be_a_full_sha(self):
        for commit in ({'sha': 'a'*40}, {'sha': 'abc'}, {}, []):
            with self.subTest(commit=commit), patch.object(monitor, 'rest_json', return_value=commit):
                if commit == {'sha': 'a'*40}:
                    self.assertEqual(monitor.main_head('example/repo', 'rest'), 'a'*40)
                else:
                    with self.assertRaises(ValueError):
                        monitor.main_head('example/repo', 'rest')

    def test_the_flag_reads_main_and_a_drill_never_does(self):
        old = {**run(age=30), 'updatedAt': (dt.datetime.now(dt.timezone.utc)
                                            - dt.timedelta(hours=30)).isoformat()}
        with patch.object(monitor, 'fetch_run', return_value=old), \
                patch.object(monitor, 'main_head', return_value='a'*40) as head, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(monitor.main(['--quiet-when-current']), 0)
            self.assertEqual(monitor.main([]), 1)  # without the flag the old run is stale
            self.assertEqual(head.call_count, 1)
            monitor.main(['--quiet-when-current', '--drill-run', '7'])
            self.assertEqual(head.call_count, 1)


class RestTransport(unittest.TestCase):
    """--transport rest reads the public API with no gh CLI (a scheduled cloud session)."""

    def rest_run(self, **change):
        return {'name': 'validate', 'status': 'completed', 'conclusion': 'success', 'id': 7,
                'head_sha': 'a'*40, 'html_url': run()['url'], 'updated_at': run()['updatedAt'],
                **change}

    def test_latest_run_maps_to_the_gh_shape(self):
        page = {'total_count': 1, 'workflow_runs': [self.rest_run()]}
        with patch.object(monitor, 'rest_json', return_value=page) as rest, \
                patch.object(monitor, 'gh_json', side_effect=AssertionError('gh used')):
            got = monitor.fetch_run('example/repo', transport='rest')
        self.assertEqual(got, {'databaseId': 7, 'conclusion': 'success', 'headSha': 'a'*40,
                               'url': run()['url'], 'updatedAt': run()['updatedAt']})
        path = rest.call_args.args[0]
        self.assertIn('actions/workflows/validate.yml/runs?', path)
        for part in ('branch=main', 'event=push', 'status=completed', 'per_page=1'):
            self.assertIn(part, path)

    def test_empty_and_malformed_pages(self):
        with patch.object(monitor, 'rest_json', return_value={'workflow_runs': []}):
            self.assertIsNone(monitor.fetch_run('example/repo', transport='rest'))
        for page in ({}, [], {'workflow_runs': {}}, {'workflow_runs': [{}, {}]}):
            with self.subTest(page=page), patch.object(monitor, 'rest_json', return_value=page), \
                    self.assertRaises((ValueError, KeyError)):
                monitor.fetch_run('example/repo', transport='rest')

    def test_drill_over_rest_keeps_the_real_failed_run_rule(self):
        with patch.object(monitor, 'rest_json', return_value=self.rest_run(conclusion='failure')):
            self.assertEqual(monitor.fetch_run('example/repo', 7, transport='rest')['conclusion'],
                             'failure')
        with patch.object(monitor, 'rest_json', return_value=self.rest_run()), \
                self.assertRaises(ValueError):
            monitor.fetch_run('example/repo', 7, transport='rest')

    def test_token_is_sent_only_when_set(self):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        seen = []

        def opener(request, timeout):
            seen.append(request)
            return Response(b'{"ok": true}')

        with patch.object(monitor.urllib.request, 'urlopen', side_effect=opener):
            with patch.dict(monitor.os.environ, {}, clear=True):
                self.assertEqual(monitor.rest_json('repos/x/y'), {'ok': True})
            with patch.dict(monitor.os.environ, {'GITHUB_TOKEN': 't0k'}, clear=True):
                monitor.rest_json('repos/x/y')
        self.assertIsNone(seen[0].get_header('Authorization'))
        self.assertEqual(seen[1].get_header('Authorization'), 'Bearer t0k')
        self.assertTrue(seen[0].full_url.startswith('https://api.github.com/repos/x/y'))
        # get_header() reads both header maps, so it cannot tell where the token rides. It must
        # ride the UNREDIRECTED one: urllib copies `headers` onto the request a 3xx makes, to
        # whatever host the Location names (2026-10-27 audit, W5-08).
        self.assertNotIn('Authorization', seen[1].headers, 'the token rides a header a redirect re-sends')
        self.assertEqual(seen[1].unredirected_hdrs.get('Authorization'), 'Bearer t0k')

    def test_the_token_never_follows_a_redirect_and_a_foreign_answer_is_refused(self):
        seen = {}

        def serve(handler):
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            return server.server_address[1]

        class Elsewhere(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen['elsewhere'] = self.headers.get('Authorization')
                body = b'{"workflow_runs": []}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        elsewhere = serve(Elsewhere)

        class Redirector(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen['api'] = self.headers.get('Authorization')
                self.send_response(302)
                self.send_header('Location', f'http://localhost:{elsewhere}/collect')
                self.send_header('Content-Length', '0')
                self.end_headers()

        api = serve(Redirector)
        with patch.object(monitor, 'API', f'http://127.0.0.1:{api}'), \
                patch.dict(monitor.os.environ, {'GITHUB_TOKEN': 'dummy-not-a-real-token'}, clear=True), \
                self.assertRaises(RuntimeError):
            monitor.rest_json('repos/x/y')
        self.assertEqual(seen.get('api'), 'Bearer dummy-not-a-real-token')
        self.assertIn('elsewhere', seen, 'the redirect was never followed: the test proves nothing')
        self.assertIsNone(seen['elsewhere'], 'the token followed the redirect to another origin')

    def test_a_body_over_the_cap_is_refused_unread(self):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        big = json.dumps({'pad': 'x' * 4096}).encode()
        response = Response(big)
        with patch.object(monitor, 'MAX_BODY', 1024, create=True), \
                patch.object(monitor.urllib.request, 'urlopen', return_value=response), \
                self.assertRaises(RuntimeError):
            monitor.rest_json('repos/x/y')
        # Refused UNREAD: never more than the cap and the one byte that proves it is over (a body
        # read whole and then measured raised the same RuntimeError, re-attack of 2d254d0f).
        self.assertLessEqual(response.tell(), 1024 + 1, 'the body was read past the cap before it was refused')

    def test_repo_must_be_owner_slash_name_before_it_reaches_a_url(self):
        for repo in ('a/b?x=y', '../gists', 'a/b/c', 'a/..', '-a/b', 'a/b#c', 'a b/c', 'a/b%2F', 'a'):
            for transport in ('rest', 'gh'):
                with self.subTest(repo=repo, transport=transport), \
                        patch.object(monitor, 'rest_json', return_value={'workflow_runs': []}) as rest, \
                        patch.object(monitor, 'gh_json', return_value=[]) as gh, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(monitor.main([f'--repo={repo}', '--transport', transport]), 2)
                    self.assertEqual(json.loads(output.getvalue())['status'], 'monitor-error')
                    self.assertEqual((rest.call_count, gh.call_count), (0, 0), 'the repo reached a request')

    def test_a_cut_off_response_is_a_monitor_error(self):
        # IncompleteRead is an http.client.HTTPException, not an OSError (PR #574 review).
        class Truncated(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, *args):
                raise monitor.http.client.IncompleteRead(b'{"workflow', 100)

        with patch.object(monitor.urllib.request, 'urlopen', return_value=Truncated()), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(monitor.main(['--transport', 'rest']), 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'monitor-error')
        self.assertNotIn('workflow', output.getvalue())

    def test_api_outage_is_a_monitor_error_not_green(self):
        for error in (monitor.urllib.error.URLError('down'), ValueError('bad json')):
            with self.subTest(error=type(error)), \
                    patch.object(monitor, 'rest_json', side_effect=error), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(monitor.main(['--transport', 'rest']), 2)
                self.assertEqual(json.loads(output.getvalue())['status'], 'monitor-error')

if __name__ == '__main__':
    unittest.main()
