package db

import (
	"context"
	"embed"
	"fmt"
	"log/slog"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/pressly/goose/v3"

	// pgx stdlib adapter for goose
	_ "github.com/jackc/pgx/v5/stdlib"
)

//go:embed migrations/*.sql
var migrationFS embed.FS

// Migrate runs all pending database migrations.
func Migrate(ctx context.Context, pool *pgxpool.Pool) error {
	// goose needs database/sql, so we open via pgx stdlib adapter
	db := pool.Config().ConnConfig.ConnString()

	sqlDB, err := goose.OpenDBWithDriver("pgx", db)
	if err != nil {
		return fmt.Errorf("open db for migrations: %w", err)
	}
	defer sqlDB.Close()

	goose.SetBaseFS(migrationFS)

	if err := goose.SetDialect("postgres"); err != nil {
		return fmt.Errorf("set dialect: %w", err)
	}

	if err := goose.UpContext(ctx, sqlDB, "migrations"); err != nil {
		return fmt.Errorf("run migrations: %w", err)
	}

	version, err := goose.GetDBVersionContext(ctx, sqlDB)
	if err != nil {
		return fmt.Errorf("get db version: %w", err)
	}

	slog.Info("migrations complete", "version", version)
	return nil
}
