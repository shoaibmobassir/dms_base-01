-- Enable extensions on database init
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Load AGE and create the knowledge graph
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('legal_knowledge');
