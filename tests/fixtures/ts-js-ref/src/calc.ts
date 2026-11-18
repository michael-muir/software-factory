export function add(a: number, b: number): number {
  return a + b;
}

export function isPositive(x: number): boolean {
  return x > 0;
}

export function clamp(value: number, low: number, high: number): number {
  if (value < low) {
    return low;
  }
  if (value > high) {
    return high;
  }
  return value;
}
