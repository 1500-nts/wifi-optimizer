import json
import matplotlib.pyplot as plt

data = json.load(open("results/results.json"))
b = data["static"]["before"]
a = data["static"]["after"]

plt.bar(["Before", "After"], [b["throughput_mbps"], a["throughput_mbps"]],
        color=["#c0504d", "#2e8b57"])
plt.ylabel("Throughput (Mbps)")
plt.title("Throughput before vs after optimization")
plt.show()