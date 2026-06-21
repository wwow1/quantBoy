package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"

	"quantboy/internal/config"
	"quantboy/internal/handler"
	"quantboy/internal/repository"
	"quantboy/internal/service"
)

var logger *zap.Logger

func main() {
	// 1. 加载配置
	cfg, err := config.LoadConfigFromDir("./config", "config")
	if err != nil {
		fmt.Printf("加载配置失败: %v\n", err)
		os.Exit(1)
	}

	// 2. 初始化日志
	logger, err = initLogger(cfg.Log.Level, cfg.Log.File)
	if err != nil {
		fmt.Printf("初始化日志失败: %v\n", err)
		os.Exit(1)
	}
	defer logger.Sync()

	logger.Info("QuantBoy 服务启动中...",
		zap.Int("port", cfg.Server.Port),
		zap.String("mode", cfg.Server.Mode),
	)

	// 3. 初始化数据库
	db, err := repository.InitDB(cfg.Database.Path)
	if err != nil {
		logger.Fatal("初始化数据库失败", zap.Error(err))
	}
	defer db.Close()
	logger.Info("数据库初始化成功", zap.String("path", cfg.Database.Path))

	// 4. 创建 Repository -> Service -> Handler
	stockRepo := repository.NewStockRepository(db)
	stockService := service.NewStockService(stockRepo)
	stockHandler := handler.NewStockHandler(stockService)

	// 5. 设置路由
	router := handler.SetupRouter(stockHandler, cfg.Server.Mode)

	// 6. 启动 HTTP 服务
	addr := fmt.Sprintf(":%d", cfg.Server.Port)
	srv := &http.Server{
		Addr:    addr,
		Handler: router,
	}

	// 启动服务（在 goroutine 中运行）
	go func() {
		logger.Info("HTTP 服务已启动", zap.String("addr", addr))
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Fatal("HTTP 服务启动失败", zap.Error(err))
		}
	}()

	// 7. 优雅关闭（监听系统信号）
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("正在关闭服务...")

	// 设置关闭超时时间
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		logger.Error("服务关闭失败", zap.Error(err))
	}

	logger.Info("服务已关闭")
}

// initLogger 初始化 zap 日志
func initLogger(level string, logFile string) (*zap.Logger, error) {
	// 解析日志级别
	var zapLevel zapcore.Level
	switch level {
	case "debug":
		zapLevel = zapcore.DebugLevel
	case "info":
		zapLevel = zapcore.InfoLevel
	case "warn":
		zapLevel = zapcore.WarnLevel
	case "error":
		zapLevel = zapcore.ErrorLevel
	default:
		zapLevel = zapcore.InfoLevel
	}

	// 配置编码器
	encoderConfig := zapcore.EncoderConfig{
		TimeKey:        "time",
		LevelKey:       "level",
		NameKey:        "logger",
		CallerKey:      "caller",
		MessageKey:     "msg",
		StacktraceKey:  "stacktrace",
		LineEnding:     zapcore.DefaultLineEnding,
		EncodeLevel:    zapcore.LowercaseLevelEncoder,
		EncodeTime:     zapcore.ISO8601TimeEncoder,
		EncodeDuration: zapcore.SecondsDurationEncoder,
		EncodeCaller:   zapcore.ShortCallerEncoder,
	}

	// 创建输出目标
	var cores []zapcore.Core

	// 控制台输出
	consoleEncoder := zapcore.NewConsoleEncoder(encoderConfig)
	consoleCore := zapcore.NewCore(consoleEncoder, zapcore.AddSync(os.Stdout), zapLevel)
	cores = append(cores, consoleCore)

	// 文件输出（如果配置了日志文件）
	if logFile != "" {
		// 确保日志目录存在
		logDir := "./data"
		if _, err := os.Stat(logDir); os.IsNotExist(err) {
			os.MkdirAll(logDir, 0755)
		}

		file, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		if err != nil {
			return nil, fmt.Errorf("无法打开日志文件: %w", err)
		}
		fileEncoder := zapcore.NewJSONEncoder(encoderConfig)
		fileCore := zapcore.NewCore(fileEncoder, zapcore.AddSync(file), zapLevel)
		cores = append(cores, fileCore)
	}

	// 组合多个 Core
	core := zapcore.NewTee(cores...)

	// 创建 Logger
	logger := zap.New(core, zap.AddCaller(), zap.AddStacktrace(zapcore.ErrorLevel))

	return logger, nil
}
