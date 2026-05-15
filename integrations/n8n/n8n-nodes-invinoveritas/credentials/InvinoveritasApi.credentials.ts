export class InvinoveritasApi {
  name = 'invinoveritasApi';
  displayName = 'invinoveritas API';
  documentationUrl = 'https://api.babyblueviper.com/guide';
  properties = [
    {
      displayName: 'API Key',
      name: 'apiKey',
      type: 'string',
      typeOptions: { password: true },
      default: '',
      required: true,
      description: 'Register free at https://api.babyblueviper.com/register, then top up with Lightning.',
    },
  ];
}
