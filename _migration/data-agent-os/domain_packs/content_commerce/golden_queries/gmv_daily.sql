select order_date, sum(paid_amount) as gmv
from sales.orders
where order_date >= :start_date and order_date < :end_date
group by order_date
order by order_date
limit :limit
