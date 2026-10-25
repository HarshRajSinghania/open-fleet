import sys, threading, time
sys.path.insert(0, "src")
from counter import Counter


class Store:
    def record_visit(self):
        time.sleep(0.001)  # I/O stand-in


c = Counter(Store())
N, T = 50, 8
ts = [threading.Thread(target=lambda: [c.hit() for _ in range(N)]) for _ in range(T)]
[t.start() for t in ts]
[t.join() for t in ts]
print("expected", N * T, "got", c.count)
sys.exit(c.count != N * T)
