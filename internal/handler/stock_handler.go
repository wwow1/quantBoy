package handler

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"quantboy/internal/model"
	"quantboy/internal/service"
)

// Response 统一响应格式
type Response struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

// ImportDataRequest 导入数据请求结构
type ImportDataRequest struct {
	Stocks    []model.Stock    `json:"stocks"`
	DailyBars []model.DailyBar `json:"daily_bars"`
}

// StockHandler 股票 HTTP 处理器
type StockHandler struct {
	service *service.StockService
}

// NewStockHandler 创建 StockHandler 实例
func NewStockHandler(svc *service.StockService) *StockHandler {
	return &StockHandler{service: svc}
}

// Success 返回成功响应
func Success(c *gin.Context, data interface{}) {
	c.JSON(http.StatusOK, Response{
		Code:    0,
		Message: "success",
		Data:    data,
	})
}

// Error 返回错误响应
func Error(c *gin.Context, httpCode int, code int, message string) {
	c.JSON(httpCode, Response{
		Code:    code,
		Message: message,
	})
}

// ListStocks 获取股票列表
// GET /api/stocks
// 支持 query 参数：market（筛选市场），keyword（搜索名称/代码）
func (h *StockHandler) ListStocks(c *gin.Context) {
	// 获取查询参数
	market := c.Query("market")
	keyword := c.Query("keyword")

	// 查询所有股票
	stocks, err := h.service.QueryStocks()
	if err != nil {
		Error(c, http.StatusInternalServerError, 500, "查询股票列表失败: "+err.Error())
		return
	}

	// 过滤结果
	var result []model.Stock
	for _, stock := range stocks {
		// 市场筛选
		if market != "" && !strings.EqualFold(stock.Market, market) {
			continue
		}

		// 关键词搜索（匹配代码或名称）
		if keyword != "" {
			keywordLower := strings.ToLower(keyword)
			codeLower := strings.ToLower(stock.Code)
			nameLower := strings.ToLower(stock.Name)
			if !strings.Contains(codeLower, keywordLower) && !strings.Contains(nameLower, keywordLower) {
				continue
			}
		}

		result = append(result, stock)
	}

	// 如果结果为空，返回空数组而不是 nil
	if result == nil {
		result = []model.Stock{}
	}

	Success(c, result)
}

// GetStockInfo 获取股票基本信息
// GET /api/stocks/:code/info
func (h *StockHandler) GetStockInfo(c *gin.Context) {
	code := c.Param("code")
	if code == "" {
		Error(c, http.StatusBadRequest, 400, "股票代码不能为空")
		return
	}

	stock, err := h.service.QueryStockByCode(code)
	if err != nil {
		Error(c, http.StatusInternalServerError, 500, "查询股票信息失败: "+err.Error())
		return
	}

	if stock == nil {
		Error(c, http.StatusNotFound, 404, "股票不存在: "+code)
		return
	}

	Success(c, stock)
}

// GetDailyBars 获取日线数据
// GET /api/stocks/:code/daily
// 支持 query 参数：start_date, end_date（格式 YYYY-MM-DD）
func (h *StockHandler) GetDailyBars(c *gin.Context) {
	code := c.Param("code")
	if code == "" {
		Error(c, http.StatusBadRequest, 400, "股票代码不能为空")
		return
	}

	// 获取日期参数，默认查询最近一年的数据
	startDate := c.DefaultQuery("start_date", "1900-01-01")
	endDate := c.DefaultQuery("end_date", "2099-12-31")

	// 验证日期格式（简单校验）
	if !isValidDateFormat(startDate) {
		Error(c, http.StatusBadRequest, 400, "start_date 格式错误，应为 YYYY-MM-DD")
		return
	}
	if !isValidDateFormat(endDate) {
		Error(c, http.StatusBadRequest, 400, "end_date 格式错误，应为 YYYY-MM-DD")
		return
	}

	bars, err := h.service.QueryDailyBars(code, startDate, endDate)
	if err != nil {
		Error(c, http.StatusInternalServerError, 500, "查询日线数据失败: "+err.Error())
		return
	}

	// 如果结果为空，返回空数组而不是 nil
	if bars == nil {
		bars = []model.DailyBar{}
	}

	Success(c, bars)
}

// GetETFDailyBars 获取 ETF 日线数据
// GET /api/etfs/:code/daily
// 支持 query 参数：start_date, end_date（格式 YYYY-MM-DD）
func (h *StockHandler) GetETFDailyBars(c *gin.Context) {
	code := c.Param("code")
	if code == "" {
		Error(c, http.StatusBadRequest, 400, "ETF 代码不能为空")
		return
	}

	startDate := c.DefaultQuery("start_date", "1900-01-01")
	endDate := c.DefaultQuery("end_date", "2099-12-31")

	if !isValidDateFormat(startDate) {
		Error(c, http.StatusBadRequest, 400, "start_date 格式错误，应为 YYYY-MM-DD")
		return
	}
	if !isValidDateFormat(endDate) {
		Error(c, http.StatusBadRequest, 400, "end_date 格式错误，应为 YYYY-MM-DD")
		return
	}

	bars, err := h.service.QueryETFDailyBars(code, startDate, endDate)
	if err != nil {
		Error(c, http.StatusInternalServerError, 500, "查询 ETF 日线数据失败: "+err.Error())
		return
	}

	if bars == nil {
		bars = []model.ETFDailyBar{}
	}

	Success(c, bars)
}

// GetMinuteBars 获取分钟线数据
// GET /api/stocks/:code/minute
// 支持 query 参数：start_time, end_time（格式 YYYY-MM-DD HH:MM:SS）
func (h *StockHandler) GetMinuteBars(c *gin.Context) {
	code := c.Param("code")
	if code == "" {
		Error(c, http.StatusBadRequest, 400, "股票代码不能为空")
		return
	}

	startTime := c.DefaultQuery("start_time", "1900-01-01 00:00:00")
	endTime := c.DefaultQuery("end_time", "2099-12-31 23:59:59")

	if !isValidDateTimeFormat(startTime) {
		Error(c, http.StatusBadRequest, 400, "start_time 格式错误，应为 YYYY-MM-DD HH:MM:SS")
		return
	}
	if !isValidDateTimeFormat(endTime) {
		Error(c, http.StatusBadRequest, 400, "end_time 格式错误，应为 YYYY-MM-DD HH:MM:SS")
		return
	}

	bars, err := h.service.QueryMinuteBars(code, startTime, endTime)
	if err != nil {
		Error(c, http.StatusInternalServerError, 500, "查询分钟线数据失败: "+err.Error())
		return
	}

	if bars == nil {
		bars = []model.MinuteBar{}
	}

	Success(c, bars)
}

// ImportData 批量导入行情数据
// POST /api/stocks/import
// 接受 JSON body：{ "stocks": [...], "daily_bars": [...] }
func (h *StockHandler) ImportData(c *gin.Context) {
	var req ImportDataRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		Error(c, http.StatusBadRequest, 400, "请求数据格式错误: "+err.Error())
		return
	}

	// 导入股票基础信息
	if len(req.Stocks) > 0 {
		if err := h.service.ImportStocks(req.Stocks); err != nil {
			Error(c, http.StatusInternalServerError, 500, "导入股票信息失败: "+err.Error())
			return
		}
	}

	// 导入日线数据
	if len(req.DailyBars) > 0 {
		if err := h.service.ImportDailyBars(req.DailyBars); err != nil {
			Error(c, http.StatusInternalServerError, 500, "导入日线数据失败: "+err.Error())
			return
		}
	}

	Success(c, gin.H{
		"stocks_count":     len(req.Stocks),
		"daily_bars_count": len(req.DailyBars),
	})
}

// HealthCheck 健康检查
// GET /api/health
func (h *StockHandler) HealthCheck(c *gin.Context) {
	Success(c, gin.H{
		"status": "healthy",
	})
}

// isValidDateFormat 验证日期格式是否为 YYYY-MM-DD
func isValidDateFormat(date string) bool {
	if len(date) != 10 {
		return false
	}
	// 简单校验格式：YYYY-MM-DD
	if date[4] != '-' || date[7] != '-' {
		return false
	}
	// 校验数字部分
	for i, c := range date {
		if i == 4 || i == 7 {
			continue
		}
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

// isValidDateTimeFormat 验证时间格式是否为 YYYY-MM-DD HH:MM:SS
func isValidDateTimeFormat(value string) bool {
	if len(value) != 19 {
		return false
	}
	if value[10] != ' ' || value[13] != ':' || value[16] != ':' {
		return false
	}
	return isValidDateFormat(value[:10]) &&
		isDigits(value[11:13]) &&
		isDigits(value[14:16]) &&
		isDigits(value[17:19])
}

func isDigits(value string) bool {
	for _, c := range value {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}
