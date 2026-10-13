'use server';
import { revalidatePath } from 'next/cache';
import { prisma } from '@/lib/db';
import { runMunicipalScraper } from '@/lib/scraper/engine';

export async function runNow(formData: FormData) {
  await runMunicipalScraper(String(formData.get('id')));
  revalidatePath('/dashboard');
}

export async function setStatus(formData: FormData) {
  const status = formData.get('status') === 'PAUSED' ? 'PAUSED' : 'ACTIVE';
  await prisma.monitoredSite.update({
    where: { id: String(formData.get('id')) },
    data: { status, ...(status === 'ACTIVE' ? { consecutiveFailures: 0, lastError: null } : {}) },
  });
  revalidatePath('/dashboard');
}

export async function removeSite(formData: FormData) {
  await prisma.monitoredSite.delete({ where: { id: String(formData.get('id')) } });
  revalidatePath('/dashboard');
}
