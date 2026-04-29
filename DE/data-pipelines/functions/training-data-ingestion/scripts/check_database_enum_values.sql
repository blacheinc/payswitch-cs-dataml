-- Check the upload_status enum values in PostgreSQL
-- Run this query to see what enum values are actually defined in the database

-- Method 1: Query the enum type directly
SELECT 
    t.typname AS enum_name,
    e.enumlabel AS enum_value,
    e.enumsortorder AS sort_order
FROM pg_type t 
JOIN pg_enum e ON t.oid = e.enumtypid  
WHERE t.typname = 'upload_status'
ORDER BY e.enumsortorder;

-- Method 2: Check what values are currently being used in the training_uploads table
SELECT DISTINCT status, COUNT(*) as count
FROM training_uploads
GROUP BY status
ORDER BY status;

-- Method 3: Get the full enum definition as SQL
SELECT 
    'CREATE TYPE ' || t.typname || ' AS ENUM (' ||
    string_agg(quote_literal(e.enumlabel), ', ' ORDER BY e.enumsortorder) ||
    ');' AS enum_definition
FROM pg_type t 
JOIN pg_enum e ON t.oid = e.enumtypid  
WHERE t.typname = 'upload_status'
GROUP BY t.typname;
