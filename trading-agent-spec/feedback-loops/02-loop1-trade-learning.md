# Loop 1: Per-Trade Learning

## Trigger

Runs immediately after every trade closes. In autonomous mode, this happens in seconds.

## Process

```python
def process_completed_trade(trade):
    # All deterministic — no LLM needed
    
    record = TradeRecord(
        slug=trade.slug,
        strategy=trade.strategy,
        entry_time=trade.entry_time,
        exit_time=trade.exit_time,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        pnl=compute_pnl(trade),  # always computed, never self-reported
        hold_duration=trade.exit_time - trade.entry_time,
        regime_at_entry=trade.regime_at_entry,
        regime_at_exit=get_current_regime(),
        slippage=trade.actual_fill - trade.planned_price,
        rules_that_fired=[r for r in trade.active_rules if r.fired],
        max_adverse_excursion=compute_mae(trade),
        max_favorable_excursion=compute_mfe(trade),
    )
    
    # Immediate pattern detection
    anomalies = detect_anomalies(record)
    
    if anomalies:
        for anomaly in anomalies:
            propose_rule(anomaly, record)
    
    # Update running statistics
    update_strategy_stats(trade.strategy, record)
    update_regime_stats(record)
    
    feedback_store.append(record)
```

## Anomaly Detection

Anomaly detection runs on a **rolling window of recent trades**, not just the current trade. With 50+ trades/day, patterns emerge within hours.

```python
def detect_anomalies(record):
    anomalies = []
    recent = feedback_store.get_last_n(strategy=record.strategy, n=20)
    
    # Pattern: consistently leaving money on the table
    mfe_capture_ratios = [t.pnl / t.mfe for t in recent if t.mfe > 0]
    if mean(mfe_capture_ratios) < 0.3:
        anomalies.append(Anomaly(
            type='POOR_MFE_CAPTURE',
            metric='mfe_capture_ratio',
            current_value=mean(mfe_capture_ratios),
            threshold=0.3,
            sample_size=len(mfe_capture_ratios),
            hypothesis='TP targets too tight or trailing stop too aggressive',
            proposed_action='WIDEN_TP_OR_LOOSEN_TRAIL',
        ))
    
    # Pattern: stops consistently hit at the worst point
    mae_recovery_rate = len([
        t for t in recent 
        if t.mae > t.stop_level * 0.9 and t.pnl > 0
    ]) / len(recent)
    if mae_recovery_rate > 0.3:
        anomalies.append(Anomaly(
            type='STOP_TOO_TIGHT',
            metric='mae_recovery_rate',
            current_value=mae_recovery_rate,
            threshold=0.3,
            sample_size=len(recent),
            hypothesis='Stop within normal noise range, causing premature exits',
            proposed_action='WIDEN_STOP',
        ))
    
    # Pattern: consistent loss in specific time window
    hourly_pnl = group_by_hour(recent)
    for hour, trades in hourly_pnl.items():
        if len(trades) >= 5 and mean([t.pnl for t in trades]) < 0:
            anomalies.append(Anomaly(
                type='NEGATIVE_TIME_WINDOW',
                metric='hourly_expectancy',
                current_value=mean([t.pnl for t in trades]),
                threshold=0,
                sample_size=len(trades),
                hypothesis=f'Negative expectancy during hour {hour}',
                proposed_action='RESTRICT_TIME_WINDOW',
            ))
    
    return anomalies
```

## Key Principle

**Loop 1 proposes, it does not apply.** Every anomaly produces a rule proposal that enters a queue for Loop 2 to evaluate with proper statistical rigor. This prevents overreaction to small samples.

## Output

- Updated trade record in feedback store
- Updated running strategy statistics
- Zero or more rule proposals (with hypotheses and baselines)
