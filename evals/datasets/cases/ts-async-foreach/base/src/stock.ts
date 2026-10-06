export interface Item { id: string; qty: number }

export async function reserveAll(items: Item[], reserve: (i: Item) => Promise<void>): Promise<number> {
  let reserved = 0;
  for (const item of items) {
    await reserve(item);
    reserved += item.qty;
  }
  return reserved;
}
