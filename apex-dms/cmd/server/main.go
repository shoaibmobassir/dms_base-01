package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/apex-chambers/dms/internal/auth"
	"github.com/apex-chambers/dms/internal/config"
	"github.com/apex-chambers/dms/internal/db"
	"github.com/apex-chambers/dms/internal/matter"
	"github.com/apex-chambers/dms/internal/server"
	"github.com/joho/godotenv"
)

func main() {
	godotenv.Load()

	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})))

	if err := run(); err != nil {
		slog.Error("server failed", "error", err)
		os.Exit(1)
	}
}

func run() error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	cfg := config.Load()
	slog.Info("config loaded", "port", cfg.ServerPort)

	pool, err := db.Connect(ctx, cfg.DSN(), cfg.DBPoolMin, cfg.DBPoolMax)
	if err != nil {
		return fmt.Errorf("database: %w", err)
	}
	defer pool.Close()

	if err := db.Migrate(ctx, pool); err != nil {
		return fmt.Errorf("migrations: %w", err)
	}

	// Auth
	authRepo := auth.NewRepository(pool)
	jwtMgr := auth.NewJWTManager(cfg)
	authService := auth.NewService(authRepo, jwtMgr, cfg)
	authHandler := auth.NewHandler(authService)

	// Matters, Documents, Conversations
	matterRepo := matter.NewRepository(pool)
	matterHandler := matter.NewHandler(matterRepo)

	handler := server.New(jwtMgr, authHandler, matterHandler, cfg)
	srv := &http.Server{
		Addr:         cfg.Addr(),
		Handler:      handler,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 60 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	errCh := make(chan error, 1)
	go func() {
		slog.Info("server starting", "addr", cfg.Addr())
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			errCh <- err
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)

	select {
	case sig := <-quit:
		slog.Info("shutdown signal received", "signal", sig)
	case err := <-errCh:
		return err
	}

	shutdownCtx, shutdownCancel := context.WithTimeout(ctx, 10*time.Second)
	defer shutdownCancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("shutdown: %w", err)
	}

	slog.Info("server stopped gracefully")
	return nil
}
