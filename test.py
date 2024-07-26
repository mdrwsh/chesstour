import numpy as np
import matplotlib.pyplot as plt

def ParametricBlend(t):
  return t*t / (2.0 * (t*t - t) + 1.0);

def BezierBlend(t):
  return t * t * (3.0 - 2.0 * t);

def exp(t):
  return t**3

for x in range(100):
  plt.scatter(x/100, exp(x/100), color='black')

plt.show()
