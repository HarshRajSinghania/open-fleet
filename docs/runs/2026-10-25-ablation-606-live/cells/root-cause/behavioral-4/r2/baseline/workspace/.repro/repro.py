import sys, threading, time
sys.path.insert(0, sys.argv[1])
from counter import Counter


class Store:
    def record_visit(self):
        time.sleep(0.001)  # models real I/O latency, yields the GIL


def run(threads=8, per=50):
    c = Counter(Store())
    ts = [threading.Thread(target=lambda: [c.hit() for _ in range(per)]) for _ in range(threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return c.count, threads * per


lost = 0
for i in range(5):
    got, want = run()
    print(f"run {i}: count={got} expected={want}")
    lost += got != want
sys.exit(1 if lost else 0)
