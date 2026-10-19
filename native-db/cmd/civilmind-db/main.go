package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/premchandkpc/archMind/native-db/internal/engine"
	"github.com/premchandkpc/archMind/native-db/internal/httpapi"
)

func main() {
	dataDir := strings.TrimSpace(os.Getenv("CIVILMIND_DB_DATA_DIR"))
	if dataDir == "" {
		dataDir = ".civilmind-native-db"
	}
	token := strings.TrimSpace(os.Getenv("CIVILMIND_DB_TOKEN"))
	if token == "" {
		slog.Error("CIVILMIND_DB_TOKEN must be configured; refusing to start")
		os.Exit(2)
	}
	addr := strings.TrimSpace(os.Getenv("CIVILMIND_DB_ADDR"))
	if addr == "" {
		addr = "127.0.0.1:8091"
	}

	store, err := engine.Open(dataDir)
	if err != nil {
		slog.Error("open native database", "error", err)
		os.Exit(1)
	}
	defer func() {
		if err := store.Close(); err != nil {
			slog.Error("close native database", "error", err)
		}
	}()

	server := &http.Server{
		Addr:              addr,
		Handler:           httpapi.New(store, token),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    1 << 20,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			slog.Error("HTTP server shutdown", "error", err)
		}
	}()

	slog.Info("CivilMind Native DB listening", "addr", addr, "data_dir", dataDir)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		slog.Error("HTTP server stopped", "error", err)
		os.Exit(1)
	}
}
