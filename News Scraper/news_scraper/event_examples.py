"""Example headlines per event category, written by hand (not taken from scraped data), used to train the headline event
classifier in nlp.py without needing labelled articles. {Co}, {Co2}, {P}, {City} are filled with varied names at training time.
Add examples here when a phrasing is missed; real labelled headlines (nlp train) are added on top of these."""

EXAMPLES = {
    "Restructuring": [
        "{Co} to cut 300 jobs as growth slows", "{Co} lays off 12% of its workforce", "{Co} announces redundancies across {City} office",
        "{Co} axes 150 roles in restructure", "Layoffs hit {Co} as revenue falls", "{Co} staff told of job cuts in dawn email",
        "{Co} to impact 400 roles in reorganisation", "{Co} restructure affects a fifth of its workforce", "Sacked {Co} workers offered severance package",
        "{Co} slashes headcount by 20%", "{Co} confirms second round of layoffs this year", "{Co} to lay off hundreds amid cost crunch",
        "{Co} enters voluntary administration", "Administrators appointed to {Co}", "{Co} collapses into liquidation owing $20m",
        "{Co} closes {City} office as part of cost cuts", "{Co} to shut down its {City} operations", "{Co} files for bankruptcy protection",
        "{Co} cull hits marketing and sales teams", "Inside the {Co} redundancies: what staff were told", "{Co} job losses mount as it winds down division",
        "{Co} CEO apologises as company makes 500 people redundant", "{Co}'s severance package after mass layoffs", "{Co} downsizes after losing major contract",
        "Hundreds of jobs to go at {Co}", "{Co} swings the axe on its engineering team", "Ex-{Co} staff reveal redundancy details",
        "{Co} shifts gear as debts pile up", "{Co} warns of insolvency as creditors circle", "{Co} trims workforce in efficiency drive",
    ],
    "Leadership change": [
        "{Co} appoints {P} as chief executive officer", "{Co} names {P} as new CFO", "{Co} CEO {P} steps down after five years",
        "{Co} hires former {Co2} executive as COO", "{P} to leave {Co} as chief financial officer", "{Co} promotes {P} to chief customer officer",
        "{Co} taps {P} to lead its Asia Pacific business", "{Co} founder hands over CEO role to {P}", "{Co} names new leaders for retail and business divisions",
        "{Co} loses senior leaders amid strategy shift", "{Co} chair {P} resigns", "{Co} appoints new managing director for {City}",
        "{Co} reshapes executive team with three appointments", "{P} joins {Co} as chief technology officer", "{Co} gives acting CEO the permanent job",
        "{Co} CFO flags departure", "{Co} announces {P} to step down as CFO", "Who is {Co}'s new chief financial officer, {P}?",
        "{Co} appoints {P} to lead its {City} operation", "Senior {Co} executive {P} exits after eight years", "{Co} board ousts chief executive",
        "{Co} names interim CEO as {P} departs", "{Co} splits division and appoints dual chief officers", "{Co} appoints new executives in leadership shake-up",
    ],
    "M&A": [
        "{Co} acquires {Co2} to expand its platform", "{Co} to buy {Co2} for $200 million", "{Co} completes acquisition of {Co2}",
        "{Co} snaps up rival {Co2}", "{Co2} agrees to be acquired by {Co}", "{Co} merges with {Co2}", "{Co} in talks to acquire {Co2}",
        "{Co} takes majority stake in {Co2}", "{Co} sells its payments division to {Co2}", "{Co} completes investment in {Co2}",
        "Bids for {Co} test $2b valuation in sell-off", "{Co2} confirms sale of its stake in {Co}", "{Co} buys {City} firm in bolt-on deal",
        "{Co} acquired by {Co2} in all-cash deal", "{Co} takeover bid from {Co2} wins board backing", "{Co} divests its consulting arm",
        "{Co} to merge with {Co2} to create industry giant", "{Co} agrees deal to buy {Co2}", "{Co} offloads subsidiary to {Co2}", "{Co} swoops on {Co2}",
    ],
    "PE buyout": [
        "Private equity firm {Co2} Capital buys {Co}", "{Co} sold to private equity in $500m buyout", "{Co2} Partners takes majority stake in {Co}",
        "{Co} acquired by private equity group {Co2} Equity", "KKR to take {Co} private", "{Co} agrees to management buyout backed by {Co2} Capital",
        "Blackstone acquires {Co} from founders", "{Co} goes private in deal with {Co2} Partners", "PE-backed {Co2} Capital completes buyout of {Co}",
        "{Co} founders sell controlling stake to private equity", "Private equity circles {Co} with takeover bid", "{Co} bought out by TPG",
    ],
    "Funding round": [
        "{Co} raises $50 million in Series B", "{Co} secures $20m in new funding round", "{Co} closes $100 million Series C led by {Co2} Ventures",
        "{Co} lands seed round of $5m", "{Co} worth $2 billion after $300 million Series D", "{Co2} Ventures invests $25M in {Co}",
        "{Co} bags $12m to fuel growth", "{Co} mega raise doubles its valuation", "{Co} raises fresh capital at $1bn valuation",
        "{Co} announces $40 million funding led by {Co2} Capital", "{Co} completes capital raise of $30m", "{Co} nabs $8 million in pre-seed funding",
        "Investors pour $75m into {Co}", "{Co} secures investment from {Co2} to accelerate expansion", "{Co} closes oversubscribed Series A",
        "{Co} raises $15m round to hire engineers", "Fintech {Co} secures $320 million at $11 billion valuation", "{Co} funding round values it at $600m",
    ],
    "Expansion / new office": [
        "{Co} opens new office in {City}", "{Co} expands into {City} with new headquarters", "{Co} to double its {City} workforce",
        "{Co} launches in the US market", "{Co} opens second hub in {City}", "{Co} to hire 200 staff in {City}", "{Co} strengthens {City} presence",
        "{Co} moves into new quarters in {City}", "{Co} to grow its {City} operations", "{Co} enters the UK market", "{Co} goes on hiring spree in {City}",
        "{Co} opens flagship store in {City}", "{Co} expands to New Zealand", "{Co} unveils new {City} campus", "{Co} to create 500 jobs with new {City} site",
        "{Co} sets up regional headquarters in {City}", "{Co} expands infrastructure to the US", "{Co} steps up hiring ahead of IPO",
        "{Co} marks milestone on new {City} headquarters tower", "{Co} opens new warehouse in {City}", "{Co} relocates to bigger office in {City}",
    ],
    "Other / Unclassified": [
        "{Co} launches new AI feature for small businesses", "{Co} partners with {Co2} to streamline payments", "{Co} shares jump 12% after earnings beat",
        "Is {Co} stock a buy after its results?", "{Co} reports first-quarter revenue of $1.2 billion", "{Co} named a leader in analyst report",
        "{Co} wins award for best workplace", "How to use {Co} to create invoices", "{Co} review 2026: features, pricing and alternatives",
        "{Co} CEO {P} on why AI is a tailwind", "{Co} sponsors {City} football club for another season", "{Co} survey finds small firms optimistic",
        "{Co} patches critical security flaw", "{Co} apologises after customer data incident", "{Co} raises its prices for customers",
        "{Co} shareholders reject executive pay report", "{Co} valuation marked down by investors", "{Co} announces $1 billion share buyback",
        "{Co} raises annual revenue guidance", "Analysts lower {Co} price target", "{Co} expands partnership with {Co2}", "{Co} integrates with {Co2} assistant",
        "{Co} founder {P} to sell $700 million of shares", "{Co} faces lawsuit from former employee", "{Co} rebrands with new name and logo",
        "{Co} hosts annual customer conference in {City}", "{Co} unveils new product suite for designers", "{Co} says customers can save on bills this winter",
        "Opinion: what {Co}'s strategy means for the sector", "{Co} expands product range with new add-on", "{Co} expands into AI advertising",
        "{Co} staff bonuses overhauled after share price slump", "{Co} donates $1m to charity", "{Co} earnings call transcript",
        "{Co} outage leaves users unable to log in", "{Co} wins contract with {Co2}", "{Co} publishes guide to remote work", "{Co} acquisition of {Co2} weighs on profit",
        "{Co} restructure: what it means for rival {Co2}", "{Co} founders' stakes diverge after share sales", "{Co} CEO pay package criticised",
        "{Co} tests four-day week for staff", "{Co} boss would love to enter new markets one day", "{Co} faces questions over leadership and expansion",
        "{Co} invests in solar farms to power homes", "Court rules {Co} can performance-manage engineer", "{Co} appoints advisory board of customers",
        "{Co} marks ten years in {City}", "{Co} union recognition vote goes ahead", "{Co} opens applications for grants program",
    ],
}
NAMES = ["Acme", "Northwind", "Brightpath", "Kestrel Group", "Harbour & Co", "Zentro", "Lumen Health", "Oakridge Partners", "Pivotal", "Bluegum",
         "Meridian Logistics", "Fernhill", "Corvus", "Tandem Legal", "Sable Systems", "Wattle", "Ironbark", "Solace", "Quill", "Redgum Realty"]
PEOPLE = ["Sarah Chen", "James O'Neill", "Priya Nair", "Tom Walker", "Maria Rossi", "David Kim", "Aisha Khan", "Liam Murphy"]
CITIES = ["Sydney", "Melbourne", "London", "Manila", "Auckland", "Singapore", "Manchester", "Austin", "Brisbane", "Toronto"]
