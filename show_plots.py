import glob
import matplotlib
matplotlib.use("TkAgg")          # use a window backend (Tk ships with Python on Windows)
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

for path in sorted(glob.glob("results/*.png")):
    img = mpimg.imread(path)
    plt.figure(figsize=(12, 6))
    plt.imshow(img)
    plt.axis("off")
    plt.title(path)
    plt.tight_layout()

plt.show()   # opens one window per plot; close them to exit