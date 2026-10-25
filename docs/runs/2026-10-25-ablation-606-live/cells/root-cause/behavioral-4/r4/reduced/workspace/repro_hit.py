import sys, threading, time
sys.path.insert(0, "src")
from counter import Counter


class Store:
    def __init__(s, delay):
        s.n = 0
        s.delay = delay
        s.l = threading.Lock()

    def record_visit(s):
        time.sleep(s.delay)
        with s.l:
            s.n += 1


def run(threads, per, delay):
    st = Store(delay)
    c = Counter(st)

    def w():
        for _ in range(per):
            c.hit()

    ts = [threading.Thread(target=w) for _ in range(threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return c.count, st.n, threads * per


for th in (1, 8):
    got = run(th, 50, 0.0005)
    print("threads", th, "-> counter, store, expected =", got)
    assert got[0] == got[2], "LOST HITS"
