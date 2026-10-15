import fs from 'fs';
import path from 'path';
import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

interface AssetExtractionConfig {
  targetDirectory: string;
  domain: string;
}

const SOURCE_EXTENSIONS = new Set(['.ts', '.tsx', '.py']);
const IGNORED_SEGMENTS = new Set(['node_modules', '.git', 'dist', 'build']);

export async function extractAssetsFromDirectory(config: AssetExtractionConfig) {
  const resolvedPath = path.resolve(config.targetDirectory);

  if (!fs.existsSync(resolvedPath)) {
    throw new Error(`Target directory does not exist: ${resolvedPath}`);
  }

  const files = fs.readdirSync(resolvedPath, { recursive: true }) as string[];
  let extractedCount = 0;

  for (const file of files) {
    if (file.split(path.sep).some((seg) => IGNORED_SEGMENTS.has(seg))) continue;
    if (!SOURCE_EXTENSIONS.has(path.extname(file))) continue;

    const fullPath = path.join(resolvedPath, file);
    if (!fs.statSync(fullPath).isFile()) continue;
    const content = fs.readFileSync(fullPath, 'utf8');

    const matches = content.match(/(class|function|const)\s+([A-Za-z0-9_]+)/g);
    if (!matches || matches.length === 0) continue;

    const assetName = path.basename(file, path.extname(file));
    const keywords = Array.from(new Set(matches.map((m) => m.split(/\s+/)[1])));

    await prisma.assetRegistry.upsert({
      where: { assetName },
      update: { keywords, filePath: fullPath },
      create: {
        assetName,
        domain: config.domain,
        keywords,
        filePath: fullPath,
        status: 'INDEXED',
      },
    });

    extractedCount++;
  }

  console.log(`[Asset Extractor] Successfully indexed ${extractedCount} assets from ${config.targetDirectory}`);
  return { success: true, extractedCount };
}
