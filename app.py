import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import requests
import pandas as pd
import streamlit as st
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

st.set_page_config(page_title='Customer Signal | Executive Intelligence', page_icon='📡', layout='wide')
st.title('📡 Customer Signal')
st.caption('Executive customer intelligence · v0.2 · Public feedback, with source-level transparency')

HEADERS={'User-Agent':'CustomerSignalResearch/0.2 (public customer feedback analysis)'}
THEMES={
 'Account & login':['login','log in','sign in','password','account','verification','locked out','authentication'],
 'App reliability':['crash','freeze','glitch','bug','broken','loading','slow','not working','doesn’t work','does not work'],
 'Pricing & value':['expensive','price','pricing','cost','subscription','fee','value'],
 'Ordering & delivery':['order','pickup','pick up','delivery','wait','store','location','shipping'],
 'Payments & refunds':['payment','charged','refund','card','balance','checkout','billing'],
 'Rewards & loyalty':['reward','points','stars','loyalty','bonus','coupon'],
 'Features & usability':['feature','interface','design','update','search','navigation','option','wish','please add'],
 'Support & service':['support','customer service','representative','help desk','response','staff'],
}
ACTIONS={
 'Account & login':'Investigate authentication failures and improve account recovery.',
 'App reliability':'Triage high-severity bugs by device, version and reproducible symptoms.',
 'Pricing & value':'Clarify pricing and investigate perceived value gaps.',
 'Ordering & delivery':'Audit order status, fulfillment expectations and location selection.',
 'Payments & refunds':'Improve failed-payment handling, refund tracking and billing clarity.',
 'Rewards & loyalty':'Make reward eligibility, progress and redemption clearer.',
 'Features & usability':'Test navigation friction and prioritize repeated feature requests.',
 'Support & service':'Review support response times and unresolved customer journeys.',
}

def apple_search(brand, product, limit=2):
    q=product or brand
    r=requests.get('https://itunes.apple.com/search',params={'term':q,'entity':'software','country':'us','limit':15},headers=HEADERS,timeout=12)
    r.raise_for_status()
    candidates=r.json().get('results',[])
    # Require brand/product name overlap; never silently pick unrelated app.
    terms=set(re.findall(r'[a-z0-9]+',q.lower()))-{'app','mobile','the'}
    ranked=sorted(candidates,key=lambda a:len(terms & set(re.findall(r'[a-z0-9]+',a.get('trackName','').lower()))),reverse=True)
    return ranked[:limit]

def apple_reviews(app_id,days):
    rows=[]
    for page in range(1,4):
        url=f'https://itunes.apple.com/us/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json'
        r=requests.get(url,headers=HEADERS,timeout=12)
        if not r.ok: break
        for e in r.json().get('feed',{}).get('entry',[]):
            if 'im:rating' not in e: continue
            rows.append({'date':e.get('updated',{}).get('label','')[:10],'rating':e['im:rating'].get('label'),'text':e.get('content',{}).get('label',''),'source':'Apple App Store','url':e.get('link',{}).get('attributes',{}).get('href',url)})
    return rows

def google_search(product):
    from google_play_scraper import search
    results=search(product,lang='en',country='us',n_hits=10)
    return results[:5]

def google_reviews(app_id):
    from google_play_scraper import reviews, Sort
    entries,_=reviews(app_id,lang='en',country='us',sort=Sort.NEWEST,count=200)
    return [{'date':str(e.get('at',''))[:10],'rating':e.get('score'),'text':e.get('content',''),'source':'Google Play','url':f'https://play.google.com/store/apps/details?id={quote(app_id)}'} for e in entries]

def reddit_posts(query):
    # Public JSON is often blocked or rate-limited on cloud hosting. Fail transparently.
    url='https://www.reddit.com/search.json'
    r=requests.get(url,params={'q':f'"{query}"','sort':'new','limit':75,'t':'year','type':'link'},headers={'User-Agent':'CustomerSignalResearch/0.2 (educational demo)'},timeout=12)
    r.raise_for_status()
    data=r.json()
    rows=[]
    for item in data.get('data',{}).get('children',[]):
        p=item.get('data',{})
        body=(p.get('title','')+' '+p.get('selftext','')).strip()
        if not body:continue
        rows.append({'date':datetime.fromtimestamp(p.get('created_utc',0),tz=timezone.utc).strftime('%Y-%m-%d'),'rating':None,'text':body,'source':'Reddit posts','url':'https://www.reddit.com'+p.get('permalink','')})
    return rows

def analyze(data):
    df=pd.DataFrame(data)
    if df.empty:return df
    df['text']=df['text'].fillna('').astype(str).str.strip()
    df=df[df.text.str.len().ge(15)].copy()
    df=df.drop_duplicates(subset=['source','text'])
    analyzer=SentimentIntensityAnalyzer()
    df['score']=df.text.map(lambda s:analyzer.polarity_scores(s)['compound'])
    df['sentiment']=df.score.map(lambda x:'Positive' if x>=0.05 else ('Negative' if x<=-0.05 else 'Neutral'))
    def themes(t):
        t=t.lower()
        return [name for name,words in THEMES.items() if any(re.search(r'(?<!\w)'+re.escape(w)+r'(?!\w)',t) for w in words)] or ['Uncategorized']
    df['themes']=df.text.map(themes)
    return df

with st.sidebar:
    st.header('Research scope')
    brand=st.text_input('Brand / company / website','Starbucks')
    product=st.text_input('Product or app (optional)','Starbucks')
    days=st.selectbox('Lookback period (days)',[30,90,180,365],index=1)
    st.caption('App matches must be verified. Reddit public access may be unavailable; no private reviews or logins are accessed.')
    go=st.button('Generate executive briefing',type='primary',use_container_width=True)

if go:
    st.session_state.pop('signal_data',None)
    st.session_state.pop('signal_coverage',None)
    if not brand.strip():st.error('Enter a brand.');st.stop()
    rows=[]; coverage=[]
    cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).date()
    with st.spinner('Discovering public sources and collecting accessible feedback...'):
        try:
            candidates=apple_search(brand,product)
            # Require exact brand token in title or seller; do not guess arbitrary match.
            needle=brand.replace('https://','').replace('http://','').split('/')[0].split('.')[0].lower().strip()
            matches=[a for a in candidates if needle in (a.get('trackName','')+' '+a.get('sellerName','')).lower()]
            if matches:
                a=matches[0]
                ar=apple_reviews(a['trackId'],days)
                rows+=ar
                coverage.append(('Apple App Store',a.get('trackName',''),len(ar),'Retrieved'))
            else:coverage.append(('Apple App Store','No confident app match',0,'Not matched'))
        except Exception as e:coverage.append(('Apple App Store','',0,f'Unavailable: {type(e).__name__}'))
        try:
            matches=google_search(product or brand)
            needle=brand.replace('https://','').replace('http://','').split('/')[0].split('.')[0].lower().strip()
            matches=[a for a in matches if needle in (a.get('title','')+' '+a.get('developer','')).lower()]
            if matches:
                g=matches[0]; gr=google_reviews(g['appId']);rows+=gr
                coverage.append(('Google Play',g.get('title',''),len(gr),'Retrieved'))
            else:coverage.append(('Google Play','No confident app match',0,'Not matched'))
        except Exception as e:coverage.append(('Google Play','',0,f'Unavailable: {type(e).__name__}'))
        try:
            rr=reddit_posts(product or brand);rows+=rr
            coverage.append(('Reddit','Public posts (not comments)',len(rr),'Retrieved'))
        except Exception as e:coverage.append(('Reddit','Public access may be blocked',0,f'Unavailable: {type(e).__name__}'))
    st.session_state['signal_data']=rows
    st.session_state['signal_coverage']=coverage
    st.session_state['signal_cutoff']=cutoff
    st.session_state['signal_brand']=brand

if 'signal_data' in st.session_state:
    coverage=st.session_state['signal_coverage']
    cutoff=st.session_state['signal_cutoff']
    st.subheader(f"Executive briefing · {st.session_state['signal_brand']}")
    st.markdown('**Source coverage and matching**')
    st.dataframe(pd.DataFrame(coverage,columns=['Source','Matched product / scope','Fetched (before date filter)','Status']),hide_index=True,use_container_width=True)
    df=analyze(st.session_state['signal_data'])
    if df.empty:st.warning('No accessible feedback was retrieved. Try another brand or product name.');st.stop()
    df['parsed_date']=pd.to_datetime(df.date,errors='coerce',utc=True)
    df=df[df.parsed_date.dt.date.ge(cutoff)].copy()
    if df.empty:st.warning('Feedback was retrieved, but none falls within the selected lookback period. Try 180 or 365 days.');st.stop()
    c1,c2,c3=st.columns(3)
    c1.metric('Feedback items analyzed',len(df))
    c2.metric('Negative text sentiment',f"{100*df.sentiment.eq('Negative').mean():.0f}%")
    c3.metric('Sources represented',df.source.nunique())
    st.caption('Not a representative sample. Reddit posts are not verified customers. VADER sentiment and keyword themes are heuristic, not an LLM. Ratings are not substituted for text sentiment.')
    issue=[]
    for theme in THEMES:
        sub=df[df.themes.map(lambda x:theme in x)]
        if len(sub):issue.append({'Theme':theme,'Mentions':len(sub),'Negative mentions':int(sub.sentiment.eq('Negative').sum()),'Negative share':round(100*sub.sentiment.eq('Negative').mean()),'Proposed investigation':ACTIONS[theme]})
    if issue:
        issues=pd.DataFrame(issue).sort_values(['Negative mentions','Mentions'],ascending=False)
        st.subheader('What customers are struggling with')
        st.dataframe(issues,hide_index=True,use_container_width=True)
        st.markdown('### Executive action brief')
        for i,r in issues.head(3).iterrows():
            st.markdown(f"**{r['Theme']}** — {r['Negative mentions']} negative mentions in {r['Mentions']} tagged items. **Next:** {r['Proposed investigation']}")
        st.caption('Actions are investigation hypotheses, not validated root causes. A review may mention multiple themes.')
    st.subheader('What people are saying')
    st.bar_chart(df.sentiment.value_counts())
    selected=st.selectbox('Filter evidence by theme',['All']+list(THEMES))
    source=st.selectbox('Filter evidence by source',['All']+sorted(df.source.unique()))
    subset=df if selected=='All' else df[df.themes.map(lambda t:selected in t)]
    if source!='All':subset=subset[subset.source.eq(source)]
    st.dataframe(subset[['date','source','rating','sentiment','text','url']],hide_index=True,use_container_width=True)
    st.download_button('Download evidence CSV',df.drop(columns=['themes','parsed_date']).to_csv(index=False).encode('utf-8'),file_name='customer_signal_evidence.csv',mime='text/csv')
    st.info('Source matching is automated and imperfect. Verify the matched app names before using this report in a business decision. Reddit access is best-effort; a permitted authenticated API is recommended for production.')
else:
    st.info('Enter a brand and click **Generate executive briefing** to analyze accessible public app reviews and Reddit posts.')
