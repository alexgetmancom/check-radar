CREATE INDEX IF NOT EXISTS `idx_items_receipt` ON `items` (`receipt_key`);--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `idx_receipts_date` ON `receipts` (`created_date`);--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `idx_taxi_trips_date` ON `taxi_trips` (`date`);
