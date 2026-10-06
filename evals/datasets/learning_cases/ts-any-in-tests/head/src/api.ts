export interface User {
  id: number;
  name: string;
}

export const API_BASE = "https://api.example.com";

export async function fetchUser(id: number): Promise<User> {
  const res = await fetch(`${API_BASE}/users/${id}`);
  return (await res.json()) as User;
}
