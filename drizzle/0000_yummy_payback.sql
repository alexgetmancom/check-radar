CREATE TABLE IF NOT EXISTS `bot_state` (
	`key` text PRIMARY KEY NOT NULL,
	`value` text
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `items` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`receipt_key` text,
	`name` text,
	`price` real,
	`quantity` real,
	`sum` real,
	FOREIGN KEY (`receipt_key`) REFERENCES `receipts`(`key`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `receipts` (
	`key` text PRIMARY KEY NOT NULL,
	`created_date` text,
	`receive_date` text,
	`total_sum` real,
	`kkt_owner` text,
	`kkt_owner_inn` text,
	`buyer` text,
	`owner_phone` text
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `taxi_trips` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`receipt_key` text,
	`date` text,
	`tariff_class` text,
	`from_address` text,
	`to_address` text,
	`distance_km` real,
	`duration_mins` integer,
	`fare_cost` real,
	`tips_cost` real,
	`total_cost` real,
	FOREIGN KEY (`receipt_key`) REFERENCES `receipts`(`key`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS `taxi_trips_receipt_key_unique` ON `taxi_trips` (`receipt_key`);
