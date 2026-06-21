package repository

import (
	"database/sql"
	"fmt"
	"strings"

	_ "github.com/mattn/go-sqlite3"
	"quantboy/internal/model"
)

// InitDB 初始化数据库连接和建表
func InitDB(dbPath string) (*sql.DB, error) {
	db, err := sql.Open("sqlite3", dbPath)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// 测试连接
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	// 创建表
	if err := createTables(db); err != nil {
		return nil, fmt.Errorf("failed to create tables: %w", err)
	}

	return db, nil
}

// createTables 创建数据库表
func createTables(db *sql.DB) error {
	// 股票基础信息表
	stocksSQL := `
	CREATE TABLE IF NOT EXISTS stocks (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		code TEXT NOT NULL UNIQUE,
		name TEXT NOT NULL,
		market TEXT NOT NULL,
		industry TEXT,
		list_date TEXT
	);
	CREATE INDEX IF NOT EXISTS idx_stocks_code ON stocks(code);
	CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks(market);
	`

	// 日线行情表
	dailyBarsSQL := `
	CREATE TABLE IF NOT EXISTS daily_bars (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		code TEXT NOT NULL,
		date TEXT NOT NULL,
		open REAL,
		high REAL,
		low REAL,
		close REAL,
		volume REAL,
		amount REAL,
		turnover REAL,
		adj_factor REAL,
		UNIQUE(code, date)
	);
	CREATE INDEX IF NOT EXISTS idx_daily_bars_code ON daily_bars(code);
	CREATE INDEX IF NOT EXISTS idx_daily_bars_date ON daily_bars(date);
	CREATE INDEX IF NOT EXISTS idx_daily_bars_code_date ON daily_bars(code, date);
	`

	// 分钟线行情表
	minuteBarsSQL := `
	CREATE TABLE IF NOT EXISTS minute_bars (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		code TEXT NOT NULL,
		time TEXT NOT NULL,
		open REAL,
		high REAL,
		low REAL,
		close REAL,
		volume REAL,
		amount REAL,
		UNIQUE(code, time)
	);
	CREATE INDEX IF NOT EXISTS idx_minute_bars_code ON minute_bars(code);
	CREATE INDEX IF NOT EXISTS idx_minute_bars_time ON minute_bars(time);
	CREATE INDEX IF NOT EXISTS idx_minute_bars_code_time ON minute_bars(code, time);
	`

	// ETF 日线行情表
	etfDailyBarsSQL := `
	CREATE TABLE IF NOT EXISTS etf_daily_bars (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		code TEXT NOT NULL,
		date TEXT NOT NULL,
		open REAL,
		high REAL,
		low REAL,
		close REAL,
		volume REAL,
		amount REAL,
		created_at TEXT DEFAULT CURRENT_TIMESTAMP,
		UNIQUE(code, date)
	);
	CREATE INDEX IF NOT EXISTS idx_etf_code ON etf_daily_bars(code);
	CREATE INDEX IF NOT EXISTS idx_etf_date ON etf_daily_bars(date);
	CREATE INDEX IF NOT EXISTS idx_etf_code_date ON etf_daily_bars(code, date);
	`

	for _, sqlStmt := range []string{stocksSQL, dailyBarsSQL, minuteBarsSQL, etfDailyBarsSQL} {
		statements := strings.Split(sqlStmt, ";")
		for _, stmt := range statements {
			stmt = strings.TrimSpace(stmt)
			if stmt == "" {
				continue
			}
			if _, err := db.Exec(stmt); err != nil {
				return fmt.Errorf("failed to execute SQL: %s, error: %w", stmt, err)
			}
		}
	}

	return nil
}

// StockRepository 股票数据仓库
type StockRepository struct {
	db *sql.DB
}

// NewStockRepository 创建 StockRepository 实例
func NewStockRepository(db *sql.DB) *StockRepository {
	return &StockRepository{db: db}
}

// CreateStock 创建股票记录
func (r *StockRepository) CreateStock(stock *model.Stock) error {
	query := `INSERT INTO stocks (code, name, market, industry, list_date) 
              VALUES (?, ?, ?, ?, ?)`
	result, err := r.db.Exec(query, stock.Code, stock.Name, stock.Market, stock.Industry, stock.ListDate)
	if err != nil {
		return fmt.Errorf("failed to create stock: %w", err)
	}
	id, _ := result.LastInsertId()
	stock.ID = id
	return nil
}

// GetStockByCode 根据代码获取股票
func (r *StockRepository) GetStockByCode(code string) (*model.Stock, error) {
	query := `SELECT id, code, name, market, industry, list_date FROM stocks WHERE code = ?`
	row := r.db.QueryRow(query, code)

	stock := &model.Stock{}
	var industry, listDate sql.NullString
	err := row.Scan(&stock.ID, &stock.Code, &stock.Name, &stock.Market, &industry, &listDate)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get stock: %w", err)
	}
	stock.Industry = industry.String
	stock.ListDate = listDate.String
	return stock, nil
}

// ListStocks 获取股票列表
func (r *StockRepository) ListStocks() ([]model.Stock, error) {
	query := `SELECT id, code, name, market, industry, list_date FROM stocks`
	rows, err := r.db.Query(query)
	if err != nil {
		return nil, fmt.Errorf("failed to list stocks: %w", err)
	}
	defer rows.Close()

	var stocks []model.Stock
	for rows.Next() {
		var stock model.Stock
		var industry, listDate sql.NullString
		if err := rows.Scan(&stock.ID, &stock.Code, &stock.Name, &stock.Market, &industry, &listDate); err != nil {
			return nil, fmt.Errorf("failed to scan stock: %w", err)
		}
		stock.Industry = industry.String
		stock.ListDate = listDate.String
		stocks = append(stocks, stock)
	}
	return stocks, nil
}

// BatchInsertDailyBars 批量插入日线数据（使用事务）
func (r *StockRepository) BatchInsertDailyBars(bars []model.DailyBar) error {
	if len(bars) == 0 {
		return nil
	}

	tx, err := r.db.Begin()
	if err != nil {
		return fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer tx.Rollback()

	query := `INSERT OR REPLACE INTO daily_bars 
              (code, date, open, high, low, close, volume, amount, turnover, adj_factor) 
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
	stmt, err := tx.Prepare(query)
	if err != nil {
		return fmt.Errorf("failed to prepare statement: %w", err)
	}
	defer stmt.Close()

	for _, bar := range bars {
		_, err := stmt.Exec(bar.Code, bar.Date, bar.Open, bar.High, bar.Low, bar.Close,
			bar.Volume, bar.Amount, bar.Turnover, bar.AdjFactor)
		if err != nil {
			return fmt.Errorf("failed to insert daily bar: %w", err)
		}
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf("failed to commit transaction: %w", err)
	}
	return nil
}

// GetDailyBars 获取日线数据
func (r *StockRepository) GetDailyBars(code string, startDate string, endDate string) ([]model.DailyBar, error) {
	query := `SELECT id, code, date, open, high, low, close, volume, amount, turnover, adj_factor 
              FROM daily_bars WHERE code = ? AND date >= ? AND date <= ? ORDER BY date`
	rows, err := r.db.Query(query, code, startDate, endDate)
	if err != nil {
		return nil, fmt.Errorf("failed to get daily bars: %w", err)
	}
	defer rows.Close()

	var bars []model.DailyBar
	for rows.Next() {
		var bar model.DailyBar
		if err := rows.Scan(&bar.ID, &bar.Code, &bar.Date, &bar.Open, &bar.High, &bar.Low,
			&bar.Close, &bar.Volume, &bar.Amount, &bar.Turnover, &bar.AdjFactor); err != nil {
			return nil, fmt.Errorf("failed to scan daily bar: %w", err)
		}
		bars = append(bars, bar)
	}
	return bars, nil
}

// GetLatestDailyBar 获取最新日线数据（用于增量更新判断）
func (r *StockRepository) GetLatestDailyBar(code string) (*model.DailyBar, error) {
	query := `SELECT id, code, date, open, high, low, close, volume, amount, turnover, adj_factor 
              FROM daily_bars WHERE code = ? ORDER BY date DESC LIMIT 1`
	row := r.db.QueryRow(query, code)

	bar := &model.DailyBar{}
	err := row.Scan(&bar.ID, &bar.Code, &bar.Date, &bar.Open, &bar.High, &bar.Low,
		&bar.Close, &bar.Volume, &bar.Amount, &bar.Turnover, &bar.AdjFactor)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get latest daily bar: %w", err)
	}
	return bar, nil
}

// GetETFDailyBars 获取 ETF 日线数据
func (r *StockRepository) GetETFDailyBars(code string, startDate string, endDate string) ([]model.ETFDailyBar, error) {
	query := `SELECT id, code, date, COALESCE(open, 0), COALESCE(high, 0), COALESCE(low, 0),
                     COALESCE(close, 0), COALESCE(volume, 0), COALESCE(amount, 0)
              FROM etf_daily_bars WHERE code = ? AND date >= ? AND date <= ? ORDER BY date`
	rows, err := r.db.Query(query, code, startDate, endDate)
	if err != nil {
		return nil, fmt.Errorf("failed to get ETF daily bars: %w", err)
	}
	defer rows.Close()

	var bars []model.ETFDailyBar
	for rows.Next() {
		var bar model.ETFDailyBar
		if err := rows.Scan(&bar.ID, &bar.Code, &bar.Date, &bar.Open, &bar.High, &bar.Low,
			&bar.Close, &bar.Volume, &bar.Amount); err != nil {
			return nil, fmt.Errorf("failed to scan ETF daily bar: %w", err)
		}
		bars = append(bars, bar)
	}
	return bars, nil
}

// BatchInsertMinuteBars 批量插入分钟线数据（使用事务）
func (r *StockRepository) BatchInsertMinuteBars(bars []model.MinuteBar) error {
	if len(bars) == 0 {
		return nil
	}

	tx, err := r.db.Begin()
	if err != nil {
		return fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer tx.Rollback()

	query := `INSERT OR REPLACE INTO minute_bars 
              (code, time, open, high, low, close, volume, amount) 
              VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
	stmt, err := tx.Prepare(query)
	if err != nil {
		return fmt.Errorf("failed to prepare statement: %w", err)
	}
	defer stmt.Close()

	for _, bar := range bars {
		_, err := stmt.Exec(bar.Code, bar.Time, bar.Open, bar.High, bar.Low, bar.Close,
			bar.Volume, bar.Amount)
		if err != nil {
			return fmt.Errorf("failed to insert minute bar: %w", err)
		}
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf("failed to commit transaction: %w", err)
	}
	return nil
}

// GetMinuteBars 获取分钟线数据
func (r *StockRepository) GetMinuteBars(code string, startTime string, endTime string) ([]model.MinuteBar, error) {
	query := `SELECT id, code, time, open, high, low, close, volume, amount 
              FROM minute_bars WHERE code = ? AND time >= ? AND time <= ? ORDER BY time`
	rows, err := r.db.Query(query, code, startTime, endTime)
	if err != nil {
		return nil, fmt.Errorf("failed to get minute bars: %w", err)
	}
	defer rows.Close()

	var bars []model.MinuteBar
	for rows.Next() {
		var bar model.MinuteBar
		if err := rows.Scan(&bar.ID, &bar.Code, &bar.Time, &bar.Open, &bar.High, &bar.Low,
			&bar.Close, &bar.Volume, &bar.Amount); err != nil {
			return nil, fmt.Errorf("failed to scan minute bar: %w", err)
		}
		bars = append(bars, bar)
	}
	return bars, nil
}
