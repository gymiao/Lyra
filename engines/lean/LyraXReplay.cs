// Adapter only: all accounting, fills and option lifecycle use the LEAN engine.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;
using QuantConnect;
using QuantConnect.Algorithm;
using QuantConnect.Data;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;
using QuantConnect.Securities.Option;

namespace LyraX
{
    public class LyraXReplay : QCAlgorithm
    {
        private Symbol _underlying;
        private List<(Symbol Symbol, decimal Quantity)> _legs = new();
        private DateTime _entry, _exit;
        private DateTime _recoveryAt;
        private decimal _shares, _initialCash;
        private decimal _expectedEndShares;
        private bool _opened, _closed;
        private bool _hedgeStarted;
        private bool _marketOnClose;
        private string _exitAction = "close", _eventPath;
        private List<object> _events = new();

        public override void Initialize()
        {
            var body = JsonDocument.Parse(File.ReadAllText(GetParameter("lyrax-input"))).RootElement;
            _entry = DateTime.Parse(body.GetProperty("entry_at_market_time").GetString());
            _exit = DateTime.Parse(body.GetProperty("exit_at_market_time").GetString());
            _shares = body.GetProperty("underlying_shares").GetDecimal();
            if(body.TryGetProperty("expected_end_shares",out var endShares)) _expectedEndShares=endShares.GetDecimal();
            _initialCash = body.GetProperty("initial_cash").GetDecimal();
            if(body.TryGetProperty("execution_method",out var method)) _marketOnClose=method.GetString()=="market_on_close";
            if(body.TryGetProperty("exit_action",out var action)) _exitAction=action.GetString();
            if(body.TryGetProperty("recovery_at_market_time",out var recovery)) _recoveryAt=DateTime.Parse(recovery.GetString());
            _eventPath=Path.Combine(Path.GetDirectoryName(GetParameter("lyrax-input")),"engine-events.json");
            SetStartDate(_entry.Date); SetEndDate(_exitAction=="spread_assignment" || _exitAction=="spread_put_assignment" ? _recoveryAt.Date : _exitAction=="expiry" || _exitAction=="collar_assignment" ? _exit.Date.AddDays(1) : _exit.Date); SetCash(_initialCash);
            var stock = AddEquity(body.GetProperty("underlying").GetString(), Resolution.Minute, leverage: 1, dataNormalizationMode: DataNormalizationMode.Raw);
            _underlying = stock.Symbol;stock.SetFeeModel(new ConstantFeeModel(0));SetBenchmark(_underlying);
            foreach(var leg in body.GetProperty("legs").EnumerateArray())
            {
                if(leg.GetProperty("multiplier").GetDecimal() != 100)
                    throw new Exception("This fixture adapter only validates standard 100-share physical contracts");
                var symbol = QuantConnect.Symbol.CreateOption(_underlying, Market.USA, OptionStyle.American,
                    leg.GetProperty("right").GetString() == "CALL" ? OptionRight.Call : OptionRight.Put,
                    leg.GetProperty("strike").GetDecimal(), DateTime.Parse(leg.GetProperty("expiry").GetString()));
                var option = AddOptionContract(symbol, Resolution.Minute);
                option.SetFeeModel(new ContractFee(body.GetProperty("fee_per_contract").GetDecimal()));
                if(_exitAction=="assignment" || _exitAction=="spread_assignment" || _exitAction=="spread_put_assignment" || _exitAction=="collar_assignment") option.SetOptionAssignmentModel(new DefaultOptionAssignmentModel(priorExpiration:TimeSpan.FromDays(10)));
                _legs.Add((symbol, leg.GetProperty("quantity").GetDecimal()));
            }
        }

        private void RequireQuotes(Slice slice)
        {
            if(!slice.Bars.ContainsKey(_underlying) || slice.Bars[_underlying].EndTime != Time)
                throw new Exception("Missing synchronous underlying execution bar");
            foreach(var leg in _legs)
            {
                if(!slice.QuoteBars.TryGetValue(leg.Symbol,out var bar) || bar.EndTime != Time ||
                    bar.Bid == null || bar.Ask == null || bar.Bid.Close <= 0 || bar.Ask.Close < bar.Bid.Close ||
                    bar.LastBidSize < Math.Abs(leg.Quantity) || bar.LastAskSize < Math.Abs(leg.Quantity))
                    throw new Exception("Missing or invalid synchronous option leg: " + leg.Symbol);
            }
        }

        private void CheckResources()
        {
            if(Portfolio.CashBook["USD"].Amount < 0) throw new Exception("Negative cash violates replay policy");
            if(Portfolio[_underlying].Quantity < 0)
            {
                var protection=_legs.Where(x=>x.Symbol.ID.OptionRight==OptionRight.Call && Portfolio[x.Symbol].Quantity>0).ToList();
                var cash=protection.Sum(x=>Portfolio[x.Symbol].Quantity*x.Symbol.ID.StrikePrice*100);
                var shares=protection.Sum(x=>Portfolio[x.Symbol].Quantity*100);
                if(_exitAction!="spread_assignment" || shares < -Portfolio[_underlying].Quantity || cash>Portfolio.CashBook["USD"].Amount)
                    throw new Exception("Unprotected or unfunded short underlying violates replay policy");
                Log("LYRAX_RISK temporary assigned short underlying requires funded long-leg exercise: " + Portfolio[_underlying].Quantity);
            }
            decimal putCash = 0, coveredShares = 0,callExerciseCash=0;
            foreach(var leg in _legs.Where(x => Portfolio[x.Symbol].Quantity < 0))
            {
                var quantity = -Portfolio[leg.Symbol].Quantity;
                if(leg.Symbol.ID.OptionRight == OptionRight.Put) putCash += quantity*leg.Symbol.ID.StrikePrice*100;
                else
                {
                    var protections = _legs.Where(x=>x.Symbol.ID.OptionRight == OptionRight.Call &&
                        x.Symbol.ID.Date == leg.Symbol.ID.Date && Portfolio[x.Symbol].Quantity>0).ToList();
                    var protection = protections.Sum(x=>Portfolio[x.Symbol].Quantity);
                    callExerciseCash+=protections.Sum(x=>Portfolio[x.Symbol].Quantity*x.Symbol.ID.StrikePrice*100);
                    coveredShares += Math.Max(0,quantity-protection)*100;
                }
            }
            if(putCash+callExerciseCash > Portfolio.CashBook["USD"].Amount || coveredShares > Math.Max(0,Portfolio[_underlying].Quantity))
                throw new Exception("Cash put collateral or call cover is insufficient");
        }

        private void RecoverAssignment(Slice slice)
        {
            var putRecovery=_exitAction=="spread_put_assignment";
            if((_exitAction!="spread_assignment" && !putRecovery) || _hedgeStarted || (putRecovery ? Portfolio[_underlying].Quantity<=0 : Portfolio[_underlying].Quantity>=0)) return;
            var protection=_legs.Single(x=>Portfolio[x.Symbol].Quantity>0 && x.Symbol.ID.OptionRight==(putRecovery ? OptionRight.Put : OptionRight.Call));
            if(!Securities[protection.Symbol].Exchange.Hours.IsOpen(Time,false) || Time < _recoveryAt) return;
            RequireQuotes(slice);
            var quantity=Portfolio[protection.Symbol].Quantity;
            if(quantity!=decimal.Truncate(quantity) || (putRecovery ? Portfolio[_underlying].Quantity<quantity*100 : Portfolio.CashBook["USD"].Amount<quantity*protection.Symbol.ID.StrikePrice*100))
                throw new Exception("Assignment hedge lacks whole contracts or funded exercise cash");
            _hedgeStarted=true;
            foreach(var other in _legs.Where(x=>x.Symbol.ID.OptionRight!=protection.Symbol.ID.OptionRight).OrderBy(x=>Portfolio[x.Symbol].Quantity))
            {
                var remaining=Portfolio[other.Symbol].Quantity;
                if(remaining!=0) MarketOrder(other.Symbol,-remaining);
                if(Portfolio[other.Symbol].Quantity!=0) throw new Exception("Unfilled opposite wing prevents recovery");
            }
            ExerciseOption(protection.Symbol,checked((int)quantity));
            _closed=true;
        }

        public override void OnData(Slice slice)
        {
            if(!_opened && Time == _entry)
            {
                RequireQuotes(slice);
                if(_shares > 0) SubmitReplayOrder(_underlying,_shares);
                foreach(var leg in _legs.OrderByDescending(x=>x.Quantity)) SubmitReplayOrder(leg.Symbol,leg.Quantity);
                _opened = true;CheckResources();
            }
            if(_opened && !_closed && Time == _exit)
            {
                RequireQuotes(slice);
                if(_exitAction=="assignment" || _exitAction=="spread_assignment" || _exitAction=="spread_put_assignment" || _exitAction=="collar_assignment" || _exitAction=="expiry") return;
                if(_exitAction=="collar_put_exercise")
                {
                    foreach(var leg in _legs.Where(x=>Portfolio[x.Symbol].Quantity<0))
                        MarketOrder(leg.Symbol,-Portfolio[leg.Symbol].Quantity);
                    if(_legs.Any(x=>Portfolio[x.Symbol].Quantity<0)) throw new Exception("Close call obligation before delivering collar stock");
                    var put=_legs.Single(x=>x.Symbol.ID.OptionRight==OptionRight.Put && Portfolio[x.Symbol].Quantity>0);
                    var quantity=Portfolio[put.Symbol].Quantity;
                    if(quantity!=decimal.Truncate(quantity) || Portfolio[_underlying].Quantity<quantity*100) throw new Exception("Collar exercise lacks deliverable shares");
                    ExerciseOption(put.Symbol,checked((int)quantity));
                    _closed=true;CheckResources();return;
                }
                if(_exitAction == "vol_call_exercise")
                {
                    foreach(var put in _legs.Where(x=>x.Symbol.ID.OptionRight==OptionRight.Put))
                        MarketOrder(put.Symbol,-Portfolio[put.Symbol].Quantity);
                    var call=_legs.Single(x=>x.Symbol.ID.OptionRight==OptionRight.Call);
                    var quantity=Portfolio[call.Symbol].Quantity;
                    if(quantity<=0 || quantity!=decimal.Truncate(quantity) || Portfolio.CashBook["USD"].Amount<quantity*call.Symbol.ID.StrikePrice*100)
                        throw new Exception("Volatility call exercise requires funded whole contracts");
                    ExerciseOption(call.Symbol,checked((int)quantity));
                    _closed=true;CheckResources();return;
                }
                if(_exitAction == "exercise")
                {
                    foreach(var leg in _legs)
                    {
                        if(Portfolio[leg.Symbol].Quantity <= 0) throw new Exception("Explicit exercise requires long options");
                        var quantity=Portfolio[leg.Symbol].Quantity;
                        if(quantity != decimal.Truncate(quantity)) throw new Exception("Exercise requires whole contracts");
                        ExerciseOption(leg.Symbol,checked((int)quantity));
                    }
                    _closed=true;CheckResources();return;
                }
                // Close obligations before disposing of their protection/cover.
                foreach(var leg in _legs.OrderBy(x=>x.Quantity)) SubmitReplayOrder(leg.Symbol,-Portfolio[leg.Symbol].Quantity);
                if(Portfolio[_underlying].Quantity != 0) SubmitReplayOrder(_underlying,-Portfolio[_underlying].Quantity);
                _closed = true;CheckResources();
            }
            if(_opened) {RecoverAssignment(slice);CheckResources();}
        }

        private void SubmitReplayOrder(Symbol symbol,decimal quantity)
        {
            if(_marketOnClose) MarketOnCloseOrder(symbol,quantity);
            else MarketOrder(symbol,quantity);
        }

        public override void OnOrderEvent(OrderEvent orderEvent)
        {
            if(orderEvent.Status == OrderStatus.Invalid) throw new Exception("Invalid replay order: " + orderEvent);
            if(orderEvent.IsAssignment && _exitAction!="spread_assignment" && _exitAction!="spread_put_assignment") _closed=true;
            Log("LYRAX_ORDER " + orderEvent);
            if(orderEvent.Status == OrderStatus.Filled)
            {
                var order=Transactions.GetOrderById(orderEvent.OrderId);
                if(_exitAction=="expiry" && order.Type==OrderType.OptionExercise && !orderEvent.IsInTheMoney) _closed=true;
                _events.Add(new {order_id=orderEvent.OrderId, event_id=orderEvent.Id,
                    symbol=orderEvent.Symbol.Value, order_symbol=order.Symbol.Value,
                    order_type=order.Type.ToString(), utc_time=orderEvent.UtcTime.ToString("O"),
                    quantity=orderEvent.FillQuantity,price=orderEvent.FillPrice,
                    fee=orderEvent.OrderFee.Value.Amount,fee_currency=orderEvent.OrderFee.Value.Currency,
                    assignment=orderEvent.IsAssignment,in_the_money=orderEvent.IsInTheMoney});
            }
        }
        public override void OnEndOfAlgorithm()
        {
            if(!_opened || !_closed || _legs.Any(x=>Portfolio[x.Symbol].Quantity!=0) || Portfolio[_underlying].Quantity!=_expectedEndShares)
                throw new Exception("Frozen lifecycle was not completed or final shares differ");
            SetRuntimeStatistic("LyraX Fixture", "synthetic_standard_100_only");
            SetRuntimeStatistic("LyraX End Cash", Portfolio.CashBook["USD"].Amount.ToString());
            File.WriteAllText(_eventPath,JsonSerializer.Serialize(_events));
        }
        private class ContractFee : FeeModel
        {
            private decimal _fee;
            public ContractFee(decimal fee) {_fee=fee;}
            public override OrderFee GetOrderFee(OrderFeeParameters parameters)
            {
                // Explicit fixture assumption: exercise/delivery fees are zero.
                // LEAN requests fees for both exercise fills; a per-trade fee
                // must not be charged once again on the underlying delivery.
                if(parameters.Order.Type == OrderType.OptionExercise) return OrderFee.Zero;
                return new OrderFee(new CashAmount(Math.Abs(parameters.Order.Quantity)*_fee,"USD"));
            }
        }
    }
}
