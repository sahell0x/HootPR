export interface Item { id: string; qty: number }

export async function reserveAll(items: Item[], reserve: (i: Item) => Promise<void>): Promise<number> {
  let reserved = 0;
  items.forEach(async (item) => {
    await reserve(item);
    reserved += item.qty;
  });
  return reserved;
}
