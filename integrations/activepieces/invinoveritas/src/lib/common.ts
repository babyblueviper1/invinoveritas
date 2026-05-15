import { httpClient, HttpMethod } from '@activepieces/pieces-common';

export const INVINO_BASE_URL = 'https://api.babyblueviper.com';

export async function invinoRequest<T>(apiKey: string, path: string, body: unknown): Promise<T> {
  const response = await httpClient.sendRequest<T>({
    method: HttpMethod.POST,
    url: `${INVINO_BASE_URL}${path}`,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'User-Agent': 'invinoveritas-activepieces/0.0.1',
      'X-Invino-Integration': 'activepieces',
    },
    body,
  });
  return response.body;
}
