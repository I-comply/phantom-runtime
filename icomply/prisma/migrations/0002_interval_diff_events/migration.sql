-- AlterTable
ALTER TABLE "MonitoredSite" ADD COLUMN     "intervalMinutes" INTEGER NOT NULL DEFAULT 360;

-- AlterTable
ALTER TABLE "ChangeLog" ADD COLUMN     "addedText" TEXT,
ADD COLUMN     "removedText" TEXT;

-- AlterTable
ALTER TABLE "WebhookDelivery" ADD COLUMN     "event" TEXT NOT NULL DEFAULT 'change',
ALTER COLUMN "changeLogId" DROP NOT NULL;

