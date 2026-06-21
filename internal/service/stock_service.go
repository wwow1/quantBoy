package service

import (
	"fmt"

	"quantboy/internal/model"
	"quantboy/internal/repository"
)

// StockService 股票服务层
type StockService struct {
	repo *repository.StockRepository
}

// NewStockService 创建 StockService 实例
func NewStockService(repo *repository.StockRepository) *StockService {
	return &StockService{repo: repo}
}

// ImportStocks 导入股票基础信息
func (s *StockService) ImportStocks(stocks []model.Stock) error {
	for i := range stocks {
		// 检查是否已存在
		existing, err := s.repo.GetStockByCode(stocks[i].Code)
		if err != nil {
			return fmt.Errorf("failed to check existing stock %s: %w", stocks[i].Code, err)
		}

		if existing == nil {
			// 不存在则创建
			if err := s.repo.CreateStock(&stocks[i]); err != nil {
				return fmt.Errorf("failed to import stock %s: %w", stocks[i].Code, err)
			}
		}
	}
	return nil
}

// ImportDailyBars 导入日线数据
func (s *StockService) ImportDailyBars(bars []model.DailyBar) error {
	if len(bars) == 0 {
		return nil
	}

	if err := s.repo.BatchInsertDailyBars(bars); err != nil {
		return fmt.Errorf("failed to import daily bars: %w", err)
	}
	return nil
}

// ImportMinuteBars 导入分钟线数据
func (s *StockService) ImportMinuteBars(bars []model.MinuteBar) error {
	if len(bars) == 0 {
		return nil
	}

	if err := s.repo.BatchInsertMinuteBars(bars); err != nil {
		return fmt.Errorf("failed to import minute bars: %w", err)
	}
	return nil
}

// QueryStocks 查询股票列表
func (s *StockService) QueryStocks() ([]model.Stock, error) {
	stocks, err := s.repo.ListStocks()
	if err != nil {
		return nil, fmt.Errorf("failed to query stocks: %w", err)
	}
	return stocks, nil
}

// QueryStockByCode 根据代码查询股票
func (s *StockService) QueryStockByCode(code string) (*model.Stock, error) {
	stock, err := s.repo.GetStockByCode(code)
	if err != nil {
		return nil, fmt.Errorf("failed to query stock by code: %w", err)
	}
	return stock, nil
}

// QueryDailyBars 查询日线数据
func (s *StockService) QueryDailyBars(code string, startDate string, endDate string) ([]model.DailyBar, error) {
	bars, err := s.repo.GetDailyBars(code, startDate, endDate)
	if err != nil {
		return nil, fmt.Errorf("failed to query daily bars: %w", err)
	}
	return bars, nil
}

// QueryLatestDailyBar 查询最新日线数据
func (s *StockService) QueryLatestDailyBar(code string) (*model.DailyBar, error) {
	bar, err := s.repo.GetLatestDailyBar(code)
	if err != nil {
		return nil, fmt.Errorf("failed to query latest daily bar: %w", err)
	}
	return bar, nil
}

// QueryETFDailyBars 查询 ETF 日线数据
func (s *StockService) QueryETFDailyBars(code string, startDate string, endDate string) ([]model.ETFDailyBar, error) {
	bars, err := s.repo.GetETFDailyBars(code, startDate, endDate)
	if err != nil {
		return nil, fmt.Errorf("failed to query ETF daily bars: %w", err)
	}
	return bars, nil
}

// QueryMinuteBars 查询分钟线数据
func (s *StockService) QueryMinuteBars(code string, startTime string, endTime string) ([]model.MinuteBar, error) {
	bars, err := s.repo.GetMinuteBars(code, startTime, endTime)
	if err != nil {
		return nil, fmt.Errorf("failed to query minute bars: %w", err)
	}
	return bars, nil
}
