import { assertPublicUrl } from './security/ssrf';
import { validateSelector } from './scraper/extract';

export const INTERVALS = [60, 360, 1440];

export async function validateTarget(name: string, url: string, selector: string): Promise<string> {
  if (!name || name.length > 200) throw new Error('Name is required (max 200 chars)');
  if (!selector || selector.length > 500) throw new Error('Selector is required (max 500 chars)');
  try {
    validateSelector(selector);
  } catch {
    throw new Error('Invalid CSS selector');
  }
  return (await assertPublicUrl(url)).toString();
}
