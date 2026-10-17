// Monthly frozen research intents. All fills and portfolio accounting use LEAN.
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
using QuantConnect.Orders.OptionExercise;
using QuantConnect.Securities;
using QuantConnect.Securities.Option;

namespace LyraX
{
    public class LyraXMonthly : QCAlgorithm
    {
        private Symbol _stock;
        private Dictionary<string,Symbol> _stocks=new();
        private List<Cycle> _cycles=new();
        private List<object> _events=new();
        private int _index;
        private string _path;
        private decimal _fee;
        private bool _prefix;
        private DateTime? _prefixAsOf;
        private Dictionary<int,decimal> _orderEquity=new();
        private HashSet<Symbol> _scenarioOptions=new();
        private class Cycle
        {
            public DateTime Entry,Exit;
            public DateTime? DeliveryExit,Preparation,StockExit;
            public string Signal;
            public decimal Shares;
            public Dictionary<Symbol,decimal> Stocks=new();
            public List<(Symbol Symbol,decimal Quantity)> Legs=new();
            public bool Opened,Closed,Natural,RetainStock,Wheel,Prepared;
        }
        public override void Initialize()
        {
            var body=JsonDocument.Parse(File.ReadAllText(GetParameter("lyrax-input"))).RootElement;
            _prefix=body.TryGetProperty("stop_at",out _);
            if(body.TryGetProperty("prefix_as_of",out var prefixAsOf)) _prefixAsOf=DateTimeOffset.Parse(prefixAsOf.GetString()).UtcDateTime;
            _path=Path.Combine(Path.GetDirectoryName(GetParameter("lyrax-input")),"engine-events.json");
            _fee=body.GetProperty("fee_per_contract").GetDecimal();
            SetCash(body.GetProperty("initial_cash").GetDecimal());
            var stock=AddEquity(body.GetProperty("underlying").GetString(),Resolution.Minute,leverage:1,dataNormalizationMode:DataNormalizationMode.Raw);
            _stock=stock.Symbol;_stocks[_stock.Value]=_stock;stock.SetFeeModel(new StockFee(body.GetProperty("stock_commission_bps").GetDecimal()));SetBenchmark(_stock);
            if(body.TryGetProperty("stocks",out var stocks))
            foreach(var ticker in stocks.EnumerateArray())
            {
                var name=ticker.GetString();if(_stocks.ContainsKey(name)) continue;
                var security=AddEquity(name,Resolution.Minute,leverage:1,dataNormalizationMode:DataNormalizationMode.Raw);
                security.SetFeeModel(new StockFee(body.GetProperty("stock_commission_bps").GetDecimal()));
                _stocks[name]=security.Symbol;
            }
            foreach(var item in body.GetProperty("cycles").EnumerateArray())
            {
                var cycle=new Cycle {Entry=DateTime.Parse(item.GetProperty("entry_submit_at").GetString()),
                    Exit=DateTime.Parse(item.GetProperty("exit_submit_at").GetString()),
                    Signal=item.GetProperty("signal_id").GetString(),Shares=item.GetProperty("underlying_shares").GetDecimal()};
                if(item.TryGetProperty("stock_positions",out var positions))
                foreach(var position in positions.EnumerateObject()) cycle.Stocks[_stocks[position.Name]]=position.Value.GetDecimal();
                else if(cycle.Shares>0) cycle.Stocks[_stock]=cycle.Shares;
                if(item.TryGetProperty("retain_stock_after_exit",out var retainStock)) cycle.RetainStock=retainStock.GetBoolean();
                if(item.TryGetProperty("wheel",out var wheel)) cycle.Wheel=wheel.GetBoolean();
                if(item.TryGetProperty("stock_entry_submit_at",out var preparation)) cycle.Preparation=DateTime.Parse(preparation.GetString());
                if(item.TryGetProperty("stock_exit_submit_at",out var stockExit)) cycle.StockExit=DateTime.Parse(stockExit.GetString());
                if(item.TryGetProperty("delivery_exit_submit_at",out var putExit)) cycle.DeliveryExit=DateTime.Parse(putExit.GetString());
                foreach(var leg in item.GetProperty("legs").EnumerateArray())
                {
                var optionStock=leg.TryGetProperty("underlying",out var legStock)?_stocks[legStock.GetString()]:_stock;
                var symbol=QuantConnect.Symbol.CreateOption(optionStock,Market.USA,OptionStyle.American,
                        leg.GetProperty("right").GetString()=="CALL"?OptionRight.Call:OptionRight.Put,
                        leg.GetProperty("strike").GetDecimal(),DateTime.Parse(leg.GetProperty("expiry").GetString()));
                    if(!Securities.ContainsKey(symbol)) AddOptionContract(symbol,Resolution.Minute).SetFeeModel(new PerContractFee(_fee));
                    cycle.Legs.Add((symbol,leg.GetProperty("quantity").GetDecimal()));
                    if(item.TryGetProperty("natural_expiry",out var natural) && natural.GetBoolean())
                    {
                        cycle.Natural=true;
                        ((Option)Securities[symbol]).SetOptionAssignmentModel(new DefaultOptionAssignmentModel(priorExpiration:TimeSpan.Zero));
                    }
                }
                if(cycle.Entry>=cycle.Exit || (_cycles.Count>0 && cycle.Entry<=_cycles.Last().Exit))
                    throw new Exception("Monthly cycles must close before the next funded entry");
                _cycles.Add(cycle);
            }
            if(body.TryGetProperty("assignment_scenarios",out var assignments))
            foreach(var scenario in assignments.EnumerateArray())
            {
                var symbol=QuantConnect.Symbol.CreateOption(_stocks[scenario.GetProperty("underlying").GetString()],Market.USA,OptionStyle.American,
                    scenario.GetProperty("right").GetString()=="CALL"?OptionRight.Call:OptionRight.Put,
                    scenario.GetProperty("strike").GetDecimal(),DateTime.Parse(scenario.GetProperty("expiry").GetString()));
                ((Option)Securities[symbol]).SetOptionAssignmentModel(new SyntheticAssignment(
                    DateTime.Parse(scenario.GetProperty("session").GetString()),scenario.GetProperty("quantity").GetDecimal()));
                ((Option)Securities[symbol]).SetOptionExerciseModel(new SyntheticPartialExercise(scenario.GetProperty("quantity").GetDecimal()));
                _scenarioOptions.Add(symbol);
            }
            if(_cycles.Count<2 && !body.TryGetProperty("stop_at",out _)) throw new Exception("Monthly replay requires multiple frozen decisions");
            SetStartDate((_cycles.First().Preparation??_cycles.First().Entry).Date);
            SetEndDate(body.TryGetProperty("valuation_until",out var valuationUntil)?DateTime.Parse(valuationUntil.GetString()):
                       body.TryGetProperty("stop_at",out var stopAt)?DateTime.Parse(stopAt.GetString()):(_cycles.Last().StockExit??_cycles.Last().Exit).Date);
        }
        private void Quotes(Slice slice,Cycle cycle)
        {
            foreach(var symbol in cycle.Stocks.Keys.Concat(cycle.Legs.Select(x=>x.Symbol.Underlying)).Append(_stock).Distinct())
                if(!slice.Bars.TryGetValue(symbol,out var stock) || stock.EndTime!=Time) throw new Exception("Missing current stock bar");
            foreach(var leg in cycle.Legs)
                if(!slice.QuoteBars.TryGetValue(leg.Symbol,out var bar) || bar.EndTime!=Time || bar.Bid==null || bar.Ask==null ||
                    bar.Bid.Close<=0 || bar.Ask.Close<bar.Bid.Close || bar.LastBidSize<Math.Abs(leg.Quantity) || bar.LastAskSize<Math.Abs(leg.Quantity))
                    throw new Exception("Missing synchronous monthly leg quote");
        }
        public override void OnData(Slice slice)
        {
            if(_prefixAsOf.HasValue && UtcTime>_prefixAsOf.Value) return;
            if(_index>=_cycles.Count) return;
            var cycle=_cycles[_index];
            if(cycle.Closed && _index+1<_cycles.Count && Time>=_cycles[_index+1].Entry)
            {
                var next=_cycles[_index+1];
                if(Portfolio.Values.Any(x=>x.Type==SecurityType.Option && x.Quantity!=0) ||
                   _stocks.Values.Any(symbol=>Portfolio[symbol].Quantity!=(cycle.RetainStock && next.Stocks.TryGetValue(symbol,out var desired)?desired:0)))
                    throw new Exception("Previous monthly cycle has unclosed options or unexpected retained stock");
                cycle=_cycles[++_index];
            }
            if(cycle.Preparation.HasValue && !cycle.Prepared && Time==cycle.Preparation.Value)
            {
                foreach(var position in cycle.Stocks)
                {
                    if(!slice.Bars.TryGetValue(position.Key,out var bar) || bar.EndTime!=Time || Portfolio[position.Key].Quantity!=0)
                        throw new Exception("Stock preparation requires current price and an empty position");
                    Submit(position.Key,position.Value,cycle.Signal+"|PREPARE_STOCK",Portfolio.TotalPortfolioValue);
                }
                cycle.Prepared=true;
            }
            if(!cycle.Opened && Time==cycle.Entry)
            {
                Quotes(slice,cycle);
                var equity=Portfolio.TotalPortfolioValue;
                if(cycle.Wheel)
                {
                    if(cycle.Legs.Count!=1 || cycle.Legs[0].Quantity>=0) throw new Exception("Wheel requires one short obligation");
                    var leg=cycle.Legs[0];var shares=Portfolio[leg.Symbol.Underlying].Quantity;
                    if(leg.Symbol.ID.OptionRight==OptionRight.Put)
                    {
                        if(shares!=0 || Portfolio.CashBook["USD"].Amount<-leg.Quantity*(leg.Symbol.ID.StrikePrice*100+_fee))
                            throw new Exception("Wheel put requires settled full cash and no stock");
                    }
                    else if(shares!=-leg.Quantity*100) throw new Exception("Wheel call requires recorded covered stock");
                }
                foreach(var position in cycle.Stocks)
                {
                    if(cycle.Wheel) continue;
                    if(cycle.Preparation.HasValue && (!cycle.Prepared || Portfolio[position.Key].Quantity!=position.Value))
                        throw new Exception("Options require completed stock preparation; no synthetic coverage");
                    var needed=position.Value-Portfolio[position.Key].Quantity;
                    if(needed<0) throw new Exception("Unexpected excess rolling stock");
                    if(needed>0) Submit(position.Key,needed,cycle.Signal+"|OPEN",equity);
                }
                foreach(var leg in cycle.Legs.OrderByDescending(x=>x.Quantity)) Submit(leg.Symbol,leg.Quantity,cycle.Signal+"|OPEN",equity);
                cycle.Opened=true;
            }
            if(cycle.Opened && cycle.Natural && cycle.DeliveryExit.HasValue && Time==cycle.DeliveryExit.Value)
            {
                Quotes(slice,cycle);
                var equity=Portfolio.TotalPortfolioValue;
                // Do not wait for a higher-strike call's automatic exercise:
                // LEAN can assign the short first. Obtain recorded delivery
                // from an ITM protection call before the assignment boundary.
                foreach(var protection in cycle.Legs.Where(x=>x.Quantity>0 && x.Symbol.ID.OptionRight==OptionRight.Call))
                {
                    var underlying=protection.Symbol.Underlying;
                    var spot=Securities[underlying].Price;
                    var obligations=cycle.Legs.Where(x=>x.Symbol.Underlying==underlying && x.Quantity<0 && x.Symbol.ID.OptionRight==OptionRight.Call && spot>x.Symbol.ID.StrikePrice)
                        .Sum(x=>Math.Max(0,-Portfolio[x.Symbol].Quantity)*100);
                    var needed=obligations-Math.Max(0,Portfolio[underlying].Quantity);
                    if(needed>0 && spot>protection.Symbol.ID.StrikePrice)
                    {
                        var quantity=Math.Min(Portfolio[protection.Symbol].Quantity,needed/100);
                        if(quantity>0) ExerciseOption(protection.Symbol,(int)quantity,tag:cycle.Signal+"|DELIVERY_COVER");
                    }
                }
                foreach(var leg in cycle.Legs)
                {
                    var quantity=Portfolio[leg.Symbol].Quantity;
                    var stockQuantity=Portfolio[leg.Symbol.Underlying].Quantity;
                    var spot=Securities[leg.Symbol.Underlying].Price;
                    var putRisk=quantity>0 && leg.Symbol.ID.OptionRight==OptionRight.Put && spot<leg.Symbol.ID.StrikePrice && stockQuantity<quantity*100;
                    var callDelivery=cycle.Legs.Where(x=>x.Symbol.Underlying==leg.Symbol.Underlying && x.Symbol.ID.OptionRight==OptionRight.Call && spot>x.Symbol.ID.StrikePrice)
                        .Sum(x=>Math.Max(0,Portfolio[x.Symbol].Quantity)*100);
                    var callRisk=quantity<0 && leg.Symbol.ID.OptionRight==OptionRight.Call && spot>leg.Symbol.ID.StrikePrice && stockQuantity+callDelivery<-quantity*100;
                    if(putRisk || callRisk)
                        Submit(leg.Symbol,-quantity,cycle.Signal+"|CLOSE_DELIVERY_RISK",equity);
                }
            }
            if(cycle.Opened && !cycle.Closed && Time==cycle.Exit)
            {
                if(cycle.Natural)
                {
                    if(cycle.Legs.Any(x=>Portfolio[x.Symbol].Quantity!=0)) throw new Exception("Natural lifecycle has not completed before recovery");
                    var value=Portfolio.TotalPortfolioValue;
                    if(!cycle.RetainStock)
                        foreach(var symbol in _stocks.Values)
                            if(Portfolio[symbol].Quantity>0) Submit(symbol,-Portfolio[symbol].Quantity,cycle.Signal+"|CLOSE",value);
                    cycle.Closed=true;
                    return;
                }
                Quotes(slice,cycle);
                var equity=Portfolio.TotalPortfolioValue;
                foreach(var leg in cycle.Legs.OrderBy(x=>x.Quantity))
                    if(Portfolio[leg.Symbol].Quantity!=0) Submit(leg.Symbol,-Portfolio[leg.Symbol].Quantity,cycle.Signal+"|CLOSE",equity);
                if(!cycle.RetainStock)
                    foreach(var symbol in cycle.Stocks.Keys)
                        if(Portfolio[symbol].Quantity!=0) Submit(symbol,-Portfolio[symbol].Quantity,cycle.Signal+"|CLOSE",equity);
                cycle.Closed=true;
            }
            if(cycle.StockExit.HasValue && Time==cycle.StockExit.Value)
            {
                if(!cycle.Closed || cycle.Legs.Any(x=>Portfolio[x.Symbol].Quantity!=0))
                    throw new Exception("Stock exit requires actual completed option closure");
                foreach(var symbol in cycle.Stocks.Keys)
                {
                    if(!slice.Bars.TryGetValue(symbol,out var bar) || bar.EndTime!=Time || Portfolio[symbol].Quantity<0)
                        throw new Exception("Stock exit requires current prices and nonnegative holdings");
                    if(Portfolio[symbol].Quantity>0) Submit(symbol,-Portfolio[symbol].Quantity,cycle.Signal+"|CLOSE_STOCK",Portfolio.TotalPortfolioValue);
                }
            }
            if(Portfolio.CashBook["USD"].Amount<0 || _stocks.Values.Any(s=>Portfolio[s].Quantity<0)) throw new Exception("Unfunded monthly portfolio");
        }
        private void Submit(Symbol symbol,decimal quantity,string tag,decimal equity)
        {
            var ticket=MarketOnCloseOrder(symbol,quantity,tag:tag);
            _orderEquity[ticket.OrderId]=equity;
        }
        public override void OnOrderEvent(OrderEvent e)
        {
            if(e.Status==OrderStatus.Invalid) throw new Exception("Unexpected monthly order rejection");
            if(e.Status!=OrderStatus.Filled) return;
            var order=Transactions.GetOrderById(e.OrderId);
            var option=e.Symbol.SecurityType==SecurityType.Option;
            _events.Add(new {order_id=e.OrderId,event_id=e.Id,symbol=e.Symbol.Value,order_type=order.Type.ToString(),
                order_symbol=order.Symbol.Value,assignment=e.IsAssignment,in_the_money=e.IsInTheMoney,
                tag=order.Tag,utc_time=e.UtcTime.ToString("O"),quantity=e.FillQuantity,price=e.FillPrice,
                fee=e.OrderFee.Value.Amount,fee_currency=e.OrderFee.Value.Currency,pre_trade_equity=_orderEquity.TryGetValue(e.OrderId,out var value)?value:Portfolio.TotalPortfolioValue,
                underlying=option?e.Symbol.Underlying.Value:null,
                expiry=option?e.Symbol.ID.Date.ToString("yyyy-MM-dd"):null,
                right=option?(e.Symbol.ID.OptionRight==OptionRight.Call?"CALL":"PUT"):null,
                strike=option?e.Symbol.ID.StrikePrice:0});
            // A later rolling guard can stop the algorithm. Already filled
            // native receipts remain available for review after that failure.
            File.WriteAllText(_path,JsonSerializer.Serialize(_events));
            if(e.IsAssignment && !_cycles[_index].Natural && !_scenarioOptions.Contains(e.Symbol))
                throw new Exception("Unexpected monthly lifecycle event; native receipt retained");
        }
        public override void OnEndOfAlgorithm()
        {
            if(!_prefix && (_cycles.Any(x=>!x.Opened || !x.Closed) || Portfolio.Values.Any(x=>x.Quantity!=0))) throw new Exception("Monthly cycles not completed");
            File.WriteAllText(_path,JsonSerializer.Serialize(_events));
        }
        private class PerContractFee:FeeModel
        {
            private decimal _value;
            public PerContractFee(decimal value) {_value=value;}
            public override OrderFee GetOrderFee(OrderFeeParameters p)=>new OrderFee(new CashAmount(p.Order.Type==OrderType.OptionExercise?0:Math.Abs(p.Order.Quantity)*_value,"USD"));
        }
        // Deterministic synthetic fault injection via the official extension.
        // LEAN performs exercise, stock delivery, cash and event processing.
        private class SyntheticAssignment:IOptionAssignmentModel
        {
            private DateTime _day;
            private decimal _quantity;
            private bool _used;
            public SyntheticAssignment(DateTime day,decimal quantity) {_day=day.Date;_quantity=quantity;}
            public OptionAssignmentResult GetAssignment(OptionAssignmentParameters p)
            {
                var option=p.Option;
                var itm=option.Symbol.ID.OptionRight==OptionRight.Call?
                    option.Underlying.Price>option.StrikePrice:option.Underlying.Price<option.StrikePrice;
                if(!_used && option.LocalTime.Date==_day && itm && option.Holdings.Quantity<=-_quantity)
                {
                    _used=true;
                    return new OptionAssignmentResult(_quantity,"SYNTHETIC_EXPLICIT_PARTIAL_ASSIGNMENT");
                }
                // Automatic expiry is handled by LEAN's expiry/delisting
                // path. Do not schedule a second assignment from a stale
                // previous-day quote at the expiry midnight boundary.
                return OptionAssignmentResult.Null;
            }
        }
        private class SyntheticPartialExercise:DefaultExerciseModel
        {
            private decimal _quantity;
            public SyntheticPartialExercise(decimal quantity) {_quantity=quantity;}
            public override IEnumerable<OrderEvent> OptionExercise(Option option,OptionExerciseOrder order)
            {
                // This pinned brokerage converts a model's nonzero quantity
                // to a full-position notification. Limit this tagged synthetic
                // exercise through the official model extension, then delegate
                // all contract and physical delivery arithmetic to LEAN.
                if(order.Tag=="SYNTHETIC_EXPLICIT_PARTIAL_ASSIGNMENT")
                {
                    var partial=new OptionExerciseOrder(order.Symbol,Math.Min(order.Quantity,_quantity),order.Time,order.Tag);
                    return base.OptionExercise(option,partial).Select(e=>{e.OrderId=order.Id;return e;});
                }
                return base.OptionExercise(option,order);
            }
        }
        private class StockFee:FeeModel
        {
            private decimal _bps;
            public StockFee(decimal bps) {_bps=bps;}
            public override OrderFee GetOrderFee(OrderFeeParameters p)=>new OrderFee(new CashAmount(Math.Abs(p.Order.Quantity)*p.Security.Price*_bps/10000,"USD"));
        }
    }
}
