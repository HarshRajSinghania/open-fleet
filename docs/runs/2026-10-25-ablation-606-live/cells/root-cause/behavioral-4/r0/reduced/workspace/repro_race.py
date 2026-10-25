import sys, time, threading
sys.path.insert(0, "src")
from counter import Counter

class Store:
    def __init__(self, delay): self.delay = delay
    def record_visit(self): time.sleep(self.delay)  # models I/O

def run(delay, n=50, per=20):
    c = Counter(Store(delay))
    ts = [threading.Thread(target=lambda: [c.hit() for _ in range(per)]) for _ in range(n)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return c.count, n * per

if __name__ == "__main__":
    for d in (0, 0.0001):
        got, exp = run(d)
        print("delay", d, "got", got, "expected", exp)
        assert got == exp, "LOST UPDATES"
