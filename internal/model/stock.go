package model

// Stock 股票基础信息
type Stock struct {
	ID       int64  `json:"id"`
	Code     string `json:"code"`      // 股票代码，如 000001
	Name     string `json:"name"`      // 股票名称
	Market   string `json:"market"`    // 市场：SH/SZ
	Industry string `json:"industry"`  // 行业
	ListDate string `json:"list_date"` // 上市日期
}

// DailyBar 日线行情
type DailyBar struct {
	ID        int64   `json:"id"`
	Code      string  `json:"code"`
	Date      string  `json:"date"` // 日期 YYYY-MM-DD
	Open      float64 `json:"open"`
	High      float64 `json:"high"`
	Low       float64 `json:"low"`
	Close     float64 `json:"close"`
	Volume    float64 `json:"volume"`     // 成交量
	Amount    float64 `json:"amount"`     // 成交额
	Turnover  float64 `json:"turnover"`   // 换手率
	AdjFactor float64 `json:"adj_factor"` // 复权因子
}

// ETFDailyBar ETF 日线行情
type ETFDailyBar struct {
	ID     int64   `json:"id"`
	Code   string  `json:"code"`
	Date   string  `json:"date"` // 日期 YYYY-MM-DD
	Open   float64 `json:"open"`
	High   float64 `json:"high"`
	Low    float64 `json:"low"`
	Close  float64 `json:"close"`
	Volume float64 `json:"volume"`
	Amount float64 `json:"amount"`
}

// MinuteBar 分钟线行情
type MinuteBar struct {
	ID     int64   `json:"id"`
	Code   string  `json:"code"`
	Time   string  `json:"time"` // 时间 YYYY-MM-DD HH:MM:SS
	Open   float64 `json:"open"`
	High   float64 `json:"high"`
	Low    float64 `json:"low"`
	Close  float64 `json:"close"`
	Volume float64 `json:"volume"`
	Amount float64 `json:"amount"`
}
