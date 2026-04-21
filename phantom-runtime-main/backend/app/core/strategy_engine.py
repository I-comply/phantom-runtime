from sqlalchemy.orm import Session
from app.core.models_v3 import Strategy, StrategyExecution, EventV3
from app.core.event_engine_v3 import EventEngineV3
from typing import Dict, Any, List
from datetime import datetime, timezone
import logging
import json

logger = logging.getLogger(__name__)

class StrategyEngine:
    """Plugin-based strategy execution engine"""
    
    # Built-in strategy templates
    BUILTIN_STRATEGIES = {
        'arbitrage': '''
# Arbitrage Strategy
# Detects price differences across events

result = {
    "opportunities": [],
    "total_events_analyzed": len(events)
}

for i in range(len(events) - 1):
    if events[i].get('price') and events[i+1].get('price'):
        price_diff = float(events[i+1]['price']) - float(events[i]['price'])
        if abs(price_diff) > config.get('threshold', 100):
            result["opportunities"].append({
                "event_1": events[i]['id'],
                "event_2": events[i+1]['id'],
                "price_diff": price_diff
            })
''',
        'anomaly_detector': '''
# Anomaly Detection Strategy
# Flags unusual patterns in event stream

result = {
    "anomalies": [],
    "analysis_complete": True
}

if len(events) < 10:
    result["status"] = "insufficient_data"
else:
    amounts = [float(e.get('amount', 0)) for e in events if 'amount' in e]
    if amounts:
        avg = sum(amounts) / len(amounts)
        for e in events:
            if 'amount' in e and abs(float(e['amount']) - avg) > avg * 2:
                result["anomalies"].append({
                    "event_id": e['id'],
                    "amount": e['amount'],
                    "deviation": abs(float(e['amount']) - avg)
                })
''',
        'yield_optimizer': '''
# Yield Optimization Strategy
# Calculates optimal allocation

result = {
    "recommended_allocation": {},
    "expected_yield": 0
}

balances = state.get('balances', {})
for asset, amount in balances.items():
    result["recommended_allocation"][asset] = float(amount) * config.get('yield_rate', 0.05)
    result["expected_yield"] += result["recommended_allocation"][asset]
'''
    }
    
    @staticmethod
    def create_strategy(
        db: Session,
        name: str,
        strategy_type: str,
        code: str = None,
        config: Dict[str, Any] = None,
        tenant_id: str = None
    ) -> Strategy:
        """Create new strategy"""
        
        # Use built-in template if code not provided
        if not code and strategy_type in StrategyEngine.BUILTIN_STRATEGIES:
            code = StrategyEngine.BUILTIN_STRATEGIES[strategy_type]
        
        strategy = Strategy(
            tenant_id=tenant_id,
            name=name,
            strategy_type=strategy_type,
            code=code,
            config=config or {}
        )
        
        db.add(strategy)
        db.commit()
        db.refresh(strategy)
        return strategy
    
    @staticmethod
    def execute_strategy(
        db: Session,
        strategy_id: str,
        entity_id: str,
        emit_events: bool = True
    ) -> StrategyExecution:
        """Execute strategy on entity"""
        
        strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if not strategy or not strategy.is_active:
            raise ValueError(f"Strategy {strategy_id} not found or inactive")
        
        # Create execution record
        execution = StrategyExecution(
            strategy_id=strategy_id,
            entity_id=entity_id,
            status='running'
        )
        db.add(execution)
        db.commit()
        
        try:
            # Get events for analysis
            events = EventEngineV3.get_entity_chain(db, entity_id)
            events_data = [
                {
                    'id': e.id,
                    'event_type': e.event_type,
                    'block_index': e.block_index,
                    **e.payload
                }
                for e in events
            ]
            
            # Get current state (simplified)
            state = {}
            for event in events:
                if event.event_type in ['init', 'update']:
                    state.update(event.payload)
            
            # Execute strategy code
            result = StrategyEngine._execute_code(
                strategy.code,
                events_data,
                state,
                strategy.config
            )
            
            execution.input_events = [e.id for e in events]
            execution.output_events = []
            
            # Emit result as new event if enabled
            if emit_events and result:
                output_event = EventEngineV3.create_event(
                    db=db,
                    entity_id=entity_id,
                    event_type=f"strategy_{strategy.strategy_type}",
                    payload=result,
                    source='agent',
                    created_by=f"strategy:{strategy_id}"
                )
                execution.output_events = [output_event.id]
            
            execution.result = result
            execution.status = 'completed'
            execution.completed_at = datetime.now(timezone.utc)
            
        except Exception as e:
            logger.error(f"Strategy execution failed: {e}")
            execution.status = 'failed'
            execution.error = str(e)
            execution.completed_at = datetime.now(timezone.utc)
        
        db.commit()
        return execution
    
    @staticmethod
    def _execute_code(code: str, events: List[Dict], state: Dict, config: Dict) -> Dict[str, Any]:
        """Execute strategy code in sandboxed environment"""
        safe_globals = {
            '__builtins__': {
                'len': len,
                'str': str,
                'int': int,
                'float': float,
                'dict': dict,
                'list': list,
                'sum': sum,
                'max': max,
                'min': min,
                'abs': abs,
                'round': round,
            }
        }
        
        safe_locals = {
            'events': events,
            'state': state.copy(),
            'config': config,
        }
        
        exec(code, safe_globals, safe_locals)
        
        if 'result' not in safe_locals:
            raise ValueError("Strategy must define 'result' variable")
        
        return safe_locals['result']
