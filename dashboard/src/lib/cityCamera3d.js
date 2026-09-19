// Seven bounded numbers: position xyz, target xyz, orthographic zoom.
// Display state only; never a simulated location or movement record.
export function normalizeCityCamera3d(value) {
  if (typeof value !== 'string' || value.length > 160
    || !/^-?\d+(?:\.\d+)?(?:,-?\d+(?:\.\d+)?){6}$/.test(value)) return null;
  const numbers = value.split(',').map(Number);
  if (numbers.some(number => !Number.isFinite(number))
    || numbers.slice(0, 6).some(number => Math.abs(number) > 10000)
    || numbers[6] < .35 || numbers[6] > 12
    || Math.hypot(...numbers.slice(0, 3).map((number, index) => number - numbers[index + 3])) < .01) return null;
  return numbers.map(number => String(Math.round(number * 1000) / 1000)).join(',');
}
