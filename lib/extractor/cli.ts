import { extractAssetsFromDirectory } from './parser';

const [targetDirectory, domain] = process.argv.slice(2);

if (!targetDirectory || !domain) {
  console.error('Usage: npm run extract -- <targetDirectory> <domain>');
  process.exit(1);
}

extractAssetsFromDirectory({ targetDirectory, domain })
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
