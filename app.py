import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import pandas as pd
import requests
import streamlit as st
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

st.set_page_config(page_title='Customer Signal | Food Delivery',page_icon='📡',layout='wide')
st.title('📡 Customer Signal')
st.caption('Food delivery competitive intelligence · v0.3 · Apple App Store + Google Play')
BRANDS=['DoorDash','Uber Eats','Grubhub']
APPS={
 'DoorDash':{'apple':719972451,'google':'com.dd.doordash','name':'DoorDash - Food Delivery'},
 'Uber Eats':{'apple':1058959277,'google':'com.ubercab.eats','name':'Uber Eats: Food Delivery'},
 'Grubhub':{'apple':302920553,'google':'com.grubhub.android','name':'Grubhub: Food Delivery'},
}
THEMES={
 'Delivery speed':['late','delay','delayed','slow delivery','wait','waiting','never arrived','driver'],
 'Fees & pricing':['fee','fees','expensive','overpriced','price','pricing','cost','tip','tipping','subscription'],
 'Refunds & payments':['refund','refunded','charge','charged','payment','credit','money back','billing'],
 'Order accuracy':['wrong order','missing item','missing food','incorrect','cold food','order accuracy','forgot'],
 'Customer support':['support','customer service','representative','agent','help center','complaint'],
 'App reliability':['crash','crashes','bug','glitch','freeze','freezes','login','sign in','not working','app update'],
 'Promotions & rewards':['promo','promotion','coupon','discount','reward','loyalty','deal'],
}
ACTIONS={
 'Delivery speed':'Investigate late-delivery patterns and ETA accuracy.',
 'Fees & pricing':'Audit fee transparency before checkout.',
 'Refunds & payments':'Review refund resolution and billing clarity.',
 'Order accuracy':'Identify order handoff and missing-item failure points.',
 'Customer support':'Audit unresolved support contacts and escalation journeys.',
 'App reliability':'Prioritize reproducible mobile app failures.',
 'Promotions & rewards':'Review promotion eligibility and redemption friction.',
}
HEADERS={'User-Agent':'CustomerSignalDemo/0.3 (public review research)'}
@st.cache_data(ttl=3600,show_spinner=False)
def apple_reviews(app_id):
    out=[]
    for page in range(1,4):
        url=f'https://itunes.apple.com/us/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json'
        r=requests.get(url,headers=HEADERS,timeout=15)
        if not r.ok:break
        for item in r.json().get('feed',{}).get('entry',[]):
            if 'im:rating' not in item:continue
            out.append({'date':item.get('updated',{}).get('label','')[:10], 'rating':item['im:rating'].get('label'), 'text':item.get('content',{}).get('label',''), 'source':'Apple App Store', 'url':item.get('link',{}).get('attributes',{}).get('href',url)})
    return out
@st.cache_data(ttl=3600,show_spinner=False)
def google_reviews(app_id):
    from google_play_scraper import reviews,Sort
    results,_=reviews(app_id,lang='en',country='us',sort=Sort.NEWEST,count=200)
    return [{'date':str(r.get('at',''))[:10],'rating':r.get('score'),'text':r.get('content',''),'source':'Google Play','url':f'https://play.google.com/store/apps/details?id={quote(app_id)}'} for r in results]

def analyze(rows,cutoff):
    df=pd.DataFrame(rows)
    if df.empty:return df
    df['text']=df.text.fillna('').astype(str).str.strip()
    df['parsed_date']=pd.to_datetime(df.date,utc=True,errors='coerce')
    df=df[(df.text.str.len()>=15)&(df.parsed_date.dt.date>=cutoff)].copy()
    df=df.drop_duplicates(['brand','source','text'])
    if df.empty:return df
    df['rating']=pd.to_numeric(df.rating,errors='coerce')
    vader=SentimentIntensityAnalyzer()
    df['sentiment_score']=df.text.map(lambda t:vader.polarity_scores(t)['compound'])
    df['sentiment']=df.sentiment_score.map(lambda s:'Positive' if s>=.05 else ('Negative' if s<=-.05 else 'Neutral'))
    def tags(t):
        t=t.lower()
        return [k for k,terms in THEMES.items() if any(re.search(r'(?<!\w)'+re.escape(w)+r'(?!\w)',t) for w in terms)] or ['Other']
    df['themes']=df.text.map(tags)
    return df

with st.sidebar:
    st.header('Analysis scope')
    days=st.selectbox('Review lookback (days)',[30,90,180,365],index=2)
    selected=st.multiselect('Compare brands',BRANDS,default=BRANDS)
    run=st.button('Analyze competitors',type='primary',use_container_width=True)
    st.caption('US English-language public review feeds. Review counts are samples, not all reviews.')
if run:
    if not selected:st.warning('Select at least one brand.');st.stop()
    rows=[];coverage=[]
    with st.spinner('Collecting app reviews...'):
        for brand in selected:
            app=APPS[brand]
            for source,collector,app_id in [('Apple App Store',apple_reviews,app['apple']),('Google Play',google_reviews,app['google'])]:
                try:
                    fetched=collector(app_id)
                    rows.extend([{**r,'brand':brand} for r in fetched])
                    coverage.append({'Brand':brand,'Source':source,'Matched app':app['name'],'Fetched':len(fetched),'Status':'Retrieved'})
                except Exception as exc:
                    coverage.append({'Brand':brand,'Source':source,'Matched app':app['name'],'Fetched':0,'Status':f'Unavailable ({type(exc).__name__})'})
    st.session_state['rows']=rows
    st.session_state['coverage']=coverage
    st.session_state['days']=days
    st.session_state['selected']=selected
if 'rows' not in st.session_state:
    st.info('Select competitors and click **Analyze competitors** to generate the report.')
    st.stop()
if days!=st.session_state['days'] or selected!=st.session_state['selected']:
    st.warning('Scope changed. Click **Analyze competitors** to refresh results.')
cutoff=(datetime.now(timezone.utc)-timedelta(days=st.session_state['days'])).date()
df=analyze(st.session_state['rows'],cutoff)
st.subheader('Source coverage')
coverage_df=pd.DataFrame(st.session_state['coverage'])
if not coverage_df.empty:
    counts=(df.groupby(['brand','source']).size().to_dict() if not df.empty else {})
    coverage_df['Reviews analyzed']=coverage_df.apply(lambda r:counts.get((r['Brand'],r['Source']),0),axis=1)
    coverage_df['Connection check']=coverage_df.apply(lambda r:'PASS' if r['Status']=='Retrieved' and r['Reviews analyzed']>0 else 'FAIL',axis=1)
    successful=int((coverage_df['Connection check']=='PASS').sum())
    total=len(coverage_df)
    st.metric('Working review sources',f'{successful}/{total}')
    if successful<total:
        st.error(f'INCOMPLETE DATA: {total-successful} brand/store connection(s) have no usable reviews in this time window. Do not treat the competitor comparison as complete.')
    else:
        st.success('All selected brand/store combinations returned usable reviews in the chosen lookback window.')
    st.dataframe(coverage_df,hide_index=True,use_container_width=True)
else:
    st.warning('No source checks available.')
if df.empty:st.warning('No reviews in the selected window. Try a longer lookback or check source availability.');st.stop()
st.subheader('Competitive overview')
summary=df.groupby('brand').agg(Reviews=('text','size'),Average_rating=('rating','mean'),Negative_share=('sentiment',lambda s:100*s.eq('Negative').mean()),Positive_share=('sentiment',lambda s:100*s.eq('Positive').mean())).reset_index()
summary.columns=['Brand','Reviews analyzed','Mean sampled star rating','Negative text (%)','Positive text (%)']
st.dataframe(summary.style.format({'Mean sampled star rating':'{:.2f}','Negative text (%)':'{:.1f}%','Positive text (%)':'{:.1f}%'}),hide_index=True,use_container_width=True)
st.caption('Ratings are calculated only from retrieved reviews, not overall store ratings. VADER text sentiment can disagree with star ratings. Samples may differ across platforms and brands.')
st.subheader('Customer pain points across competitors')
issues=[]
for brand in st.session_state['selected']:
    subset=df[df.brand==brand]
    for theme in THEMES:
        matched=subset[subset.themes.map(lambda t:theme in t)]
        neg=matched[matched.sentiment=='Negative']
        issues.append({'Brand':brand,'Theme':theme,'Tagged reviews':len(matched),'Negative mentions':len(neg),'Negative mentions per 100 reviews':round(100*len(neg)/len(subset),1) if len(subset) else 0})
issue_df=pd.DataFrame(issues)
pivot=issue_df.pivot(index='Theme',columns='Brand',values='Negative mentions per 100 reviews')
st.dataframe(pivot.style.format('{:.1f}'),use_container_width=True)
st.caption('Each cell is negative theme mentions per 100 sampled reviews; reviews can mention several themes. These are descriptive signals, not statistically representative market shares.')
st.subheader('Executive investigation priorities')
for brand in st.session_state['selected']:
    top=issue_df[issue_df.Brand==brand].sort_values('Negative mentions per 100 reviews',ascending=False).head(2)
    if top['Negative mentions'].sum()==0:continue
    st.markdown(f'**{brand}**')
    for _,r in top.iterrows():
        st.write(f"• {r['Theme']}: {r['Negative mentions']} negative mentions ({r['Negative mentions per 100 reviews']:.1f} per 100 reviews). Next: {ACTIONS[r['Theme']]}")
st.caption('These are rule-based investigation hypotheses, not AI-generated conclusions or proven root causes.')
st.subheader('Review evidence explorer')
a,b,c=st.columns(3)
brand_filter=a.selectbox('Brand',['All']+st.session_state['selected'])
source_filter=b.selectbox('Source',['All','Apple App Store','Google Play'])
theme_filter=c.selectbox('Theme',['All']+list(THEMES))
view=df
if brand_filter!='All':view=view[view.brand==brand_filter]
if source_filter!='All':view=view[view.source==source_filter]
if theme_filter!='All':view=view[view.themes.map(lambda t:theme_filter in t)]
st.dataframe(view[['brand','date','source','rating','sentiment','text','url']],hide_index=True,use_container_width=True)
st.download_button('Download evidence CSV',df.drop(columns=['parsed_date','themes']).to_csv(index=False).encode('utf-8'),file_name='customer_signal_food_delivery_reviews.csv',mime='text/csv')
st.info('Source limitations: Apple public feeds expose only a subset of reviews; Google Play uses an unofficial collector that may fail. Google Play evidence links lead to the app listing, not individual reviews. No Reddit, website scraping, or generative AI is used.')
