package handler

import (
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

// SetupRouter 设置路由
// 配置中间件和注册路由
func SetupRouter(handler *StockHandler, mode string) *gin.Engine {
	// 设置 gin 模式
	if mode == "release" {
		gin.SetMode(gin.ReleaseMode)
	} else {
		gin.SetMode(gin.DebugMode)
	}

	router := gin.New()

	// CORS 中间件 - 允许所有来源，支持 Python 客户端跨域调用
	router.Use(cors.New(cors.Config{
		AllowAllOrigins:  true,
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Accept", "Authorization", "X-Requested-With"},
		ExposeHeaders:    []string{"Content-Length", "Content-Type"},
		AllowCredentials: false,
		MaxAge:           12 * time.Hour,
	}))

	// 日志中间件
	router.Use(gin.Logger())

	// Recovery 中间件 - 从 panic 中恢复
	router.Use(gin.Recovery())

	// 注册路由
	api := router.Group("/api")
	{
		// 健康检查
		api.GET("/health", handler.HealthCheck)

		// 股票相关接口
		api.GET("/stocks", handler.ListStocks)
		api.GET("/stocks/:code/info", handler.GetStockInfo)
		api.GET("/stocks/:code/daily", handler.GetDailyBars)
		api.GET("/stocks/:code/minute", handler.GetMinuteBars)

		// ETF 相关接口
		api.GET("/etfs/:code/daily", handler.GetETFDailyBars)

		// 数据导入接口
		api.POST("/stocks/import", handler.ImportData)
	}

	return router
}
