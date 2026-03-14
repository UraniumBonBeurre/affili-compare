-- Migration: table product_classifications pour cache des résultats de classification ML
--
-- Cette table stocke en cache les résultats de classification (sklearn + LLM).
-- Permet d'éviter re-classification et de tracker l'historique.

CREATE TABLE IF NOT EXISTS product_classifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Liens
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    product_hash VARCHAR(32) NOT NULL,  -- MD5(name+brand), clé de cache

    -- Résultats
    predicted_niche TEXT NOT NULL,
    confidence_score NUMERIC(3,2) NOT NULL CHECK (confidence_score >= 0.00 AND confidence_score <= 1.00),
    source TEXT NOT NULL CHECK (source IN ('sklearn', 'llm')),  -- source de la prédiction

    -- Versioning
    model_version VARCHAR(50) DEFAULT 'v1.0',

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT pc_product_model_uq UNIQUE (product_id, model_version)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_pc_product_hash ON product_classifications(product_hash);
CREATE INDEX IF NOT EXISTS idx_pc_product_id ON product_classifications(product_id);
CREATE INDEX IF NOT EXISTS idx_pc_source ON product_classifications(source);
CREATE INDEX IF NOT EXISTS idx_pc_created_at ON product_classifications(created_at DESC);

-- Comments
COMMENT ON TABLE product_classifications IS 'Cache des résultats de classification (sklearn + LLM) pour chaque produit';
COMMENT ON COLUMN product_classifications.product_id IS 'Référence au produit classifié';
COMMENT ON COLUMN product_classifications.product_hash IS 'MD5(name+brand), clé primaire de cache';
COMMENT ON COLUMN product_classifications.predicted_niche IS 'Niche prédite (ex: gaming, office-setup)';
COMMENT ON COLUMN product_classifications.confidence_score IS 'Score de confiance (0.0-1.0)';
COMMENT ON COLUMN product_classifications.source IS 'Source de la prédiction: sklearn (default) ou llm (fallback)';
COMMENT ON COLUMN product_classifications.model_version IS 'Version du modèle utilisé (ex: v1.0)';
