import { httpClient, HttpMethod } from '@activepieces/pieces-common';

export const INVINO_BASE_URL = 'https://api.babyblueviper.com';

export async function invinoRequest<T>(apiKey: string, path: string, body: unknown): Promise<T> {
  const response = await httpClient.sendRequest<T>({
    method: HttpMethod.POST,
    url: `${INVINO_BASE_URL}${path}`,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'User-Agent': 'invinoveritas-activepieces/0.4.0',
      'X-Invino-Integration': 'activepieces',
    },
    body,
  });
  return response.body;
}

export async function invinoGet<T>(apiKey: string, path: string, x402 = false): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${apiKey}`,
    'User-Agent': 'invinoveritas-activepieces/0.4.0',
    'X-Invino-Integration': 'activepieces',
  };
  if (x402) headers['X-Payment-Scheme'] = 'x402';
  const response = await httpClient.sendRequest<T>({
    method: HttpMethod.GET,
    url: `${INVINO_BASE_URL}${path}`,
    headers,
  });
  return response.body;
}
