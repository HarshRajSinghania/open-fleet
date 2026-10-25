import sys, time, threading
sys.path.insert(0, "src")
from counter import Counter

class Store:
    def record_visit(self):
        time.sleep(0.001)  # stand-in for I/O

c = Counter(Store())
ts = [threading.Thread(target=lambda: [c.hit() for _ in range(20)]) for _ in range(20)]
[t.start() for t in ts]
[t.join() for t in ts]
print("expected 400 got", c.count)
sys.exit(c.count != 400)
