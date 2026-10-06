export function slug(s: string): string {
  return s.toLowerCase().replace(/\s+/g, "-");
}
