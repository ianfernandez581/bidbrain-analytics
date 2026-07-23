[.campaigns[] | select((.name // "") | test("Coles DOOH|Coles Prog|Q2 PubSec"))] | map({name, channel, platformMargin, totalBudget, startDate, endDate, objective, status})
