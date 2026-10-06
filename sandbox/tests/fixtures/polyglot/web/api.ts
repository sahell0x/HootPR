import { slug } from "./util";

export class Api {
  title(x: string): string {
    return slug(x);
  }
}

export function run(code: string) {
  return eval(code);
}
