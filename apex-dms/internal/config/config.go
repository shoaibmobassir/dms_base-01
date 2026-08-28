package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

// Config holds all application configuration, loaded from environment variables.
type Config struct {
	// Database
	DatabaseURL string
	DBPoolMin   int
	DBPoolMax   int

	// Redis
	RedisURL string

	// MinIO / S3
	MinioEndpoint  string
	MinioAccessKey string
	MinioSecretKey string
	MinioBucket    string
	MinioUseSSL    bool

	// JWT
	JWTSecretKey              string
	JWTAlgorithm              string
	JWTAccessTokenExpiration  time.Duration
	JWTRefreshTokenExpiration time.Duration

	// Server
	ServerPort string

	// LLM providers
	GroqAPIKey   string
	GeminiAPIKey string
	NvidiaAPIKey string

	// Retrieval sidecar
	RetrievalSidecarURL string

	// Doc-search sidecar
	DocSearchURL string
}

// Load reads configuration from environment variables with sensible defaults.
func Load() *Config {
	return &Config{
		DatabaseURL: envOr("DATABASE_URL", "postgresql://apex:apex_dev_2026@localhost:55433/apex_dms"),
		DBPoolMin:   envInt("DB_POOL_MIN", 2),
		DBPoolMax:   envInt("DB_POOL_MAX", 10),

		RedisURL: envOr("REDIS_URL", "redis://localhost:6381"),

		MinioEndpoint:  envOr("MINIO_ENDPOINT", "localhost:9000"),
		MinioAccessKey: envOr("MINIO_ACCESS_KEY", "apex_minio"),
		MinioSecretKey: envOr("MINIO_SECRET_KEY", "apex_minio_dev_2026"),
		MinioBucket:    envOr("MINIO_BUCKET", "apex-documents"),
		MinioUseSSL:    envBool("MINIO_USE_SSL", false),

		JWTSecretKey:              envOr("JWT_SECRET_KEY", "change-me-in-production"),
		JWTAlgorithm:              envOr("JWT_ALGORITHM", "HS256"),
		JWTAccessTokenExpiration:  time.Duration(envInt("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 15)) * time.Minute,
		JWTRefreshTokenExpiration: time.Duration(envInt("JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7)) * 24 * time.Hour,

		ServerPort: envOr("SERVER_PORT", "8080"),

		GroqAPIKey:   envOr("GROQ_API_KEY", ""),
		GeminiAPIKey: envOr("GEMINI_API_KEY", ""),
		NvidiaAPIKey: envOr("NVIDIA_API_KEY", ""),

		RetrievalSidecarURL: envOr("RETRIEVAL_SIDECAR_URL", "http://localhost:8000"),

		DocSearchURL: envOr("DOC_SEARCH_URL", "http://localhost:8001"),
	}
}

// DSN returns the database connection string.
func (c *Config) DSN() string {
	return c.DatabaseURL
}

// Addr returns the server listen address.
func (c *Config) Addr() string {
	return fmt.Sprintf(":%s", c.ServerPort)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}

func envBool(key string, fallback bool) bool {
	if v := os.Getenv(key); v != "" {
		if b, err := strconv.ParseBool(v); err == nil {
			return b
		}
	}
	return fallback
}
