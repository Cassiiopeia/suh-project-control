-- Step 1: benchmark_batch master table
CREATE TABLE IF NOT EXISTS benchmark_batch (
    id SERIAL PRIMARY KEY,
    prompt TEXT NOT NULL,
    system_prompt TEXT,
    temperature NUMERIC(3,2) NOT NULL DEFAULT 0.0,
    format_mode VARCHAR(20) NOT NULL,
    schema_definition TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Step 2: benchmark_result table
CREATE TABLE IF NOT EXISTS benchmark_result (
    id SERIAL PRIMARY KEY,
    batch_id INT NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    response_content TEXT,
    total_duration_ms NUMERIC(12,2),
    load_duration_ms NUMERIC(12,2),
    eval_duration_ms NUMERIC(12,2),
    prompt_eval_count INT,
    eval_count INT,
    tokens_per_second NUMERIC(6,1),
    schema_compliance VARCHAR(20) NOT NULL DEFAULT 'N/A',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_batch FOREIGN KEY (batch_id) REFERENCES benchmark_batch(id) ON DELETE CASCADE,
    CONSTRAINT unique_batch_model UNIQUE (batch_id, model_name)
);

-- Step 3: Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_result_batch ON benchmark_result(batch_id);
