# GSS - the General Social Survey

The [General Social Survey](https://gss.norc.org/) is a long-running study of American society conducted by [NORC at the University of Chicago](https://www.norc.org/) since 1972. It monitors attitudes, behaviors, and demographics of US adults with question wording deliberately kept stable across decades, which makes it one of the most widely used datasets in social science - and the ground truth this project calibrates and verifies against.

## Links

| | |
|---|---|
| GSS website | <https://gss.norc.org/> |
| Get the data | <https://gss.norc.org/us/en/gss/get-the-data.html> |
| Cumulative data file used by this project (Stata zip) | <https://gss.norc.org/content/dam/gss/get-the-data/documents/stata/GSS_stata.zip> |
| Documentation & codebooks | <https://gss.norc.org/us/en/gss/get-documentation.html> |
| GSS Data Explorer (browse questions/trends online) | <https://gssdataexplorer.norc.org/> |

The data is public and free to download; no registration or authentication is required. For the recommended citation of the current release, see the GSS documentation page above.

## The file this project uses

| | |
|---|---|
| File | GSS Cross-Sectional Cumulative Data, 1972–2024 (Release 3a, July 2026) |
| Coverage | 35 survey rounds, 75,699 respondents, 6,943 variables |
| Format | Stata `.dta` inside a 47MB zip (570MB unpacked) |
| Encoding | latin-1 (the default UTF-8 read fails on value labels) |

## How the survey works

- **Sampling.** Each round interviews roughly 3,000–4,000 adults sampled to represent the US adult population. Statistical weights correct residual imbalance; this project uses `wtssps` (person post-stratification weight), the one weight variable with 100% coverage across every round 1972–2024.
- **Split-ballot design.** Each respondent is asked only a subset of questions, so per-question valid N is well below the round's total N - core items reach ~99% of a round, rotated items ~26%.
- **Coded answers.** Responses are numeric codes with value labels (e.g. `abany`: 1 = yes, 2 = no); don't-know/refused/not-asked variants are Stata tagged-missing values.
- **2021 methodology break.** COVID forced a switch from face-to-face interviews to web/address-based sampling, so comparisons between 2021+ and earlier rounds carry a mode caveat.

## What this project takes from it

From each respondent, two kinds of information:

- **Background attributes** (persona raw material): age/year of birth, sex, race, region, education, family income bracket, work situation, marital status, number of children, religion and attendance - configured in [`config/gss_profile.yaml`](../config/gss_profile.yaml).
- **Opinions**: 26 long-running questions, hand-curated verbatim from the codebook in [`config/gss_questions.yaml`](../config/gss_questions.yaml) and broken down below.

Technical file/release settings live in [`config/gss_dataset.yaml`](../config/gss_dataset.yaml); the full acquisition-and-processing design is documented in [design/ARCHITECTURE.md](design/ARCHITECTURE.md).

## The 26 calibration questions

Question text and answer options below are quoted verbatim from [`config/gss_questions.yaml`](../config/gss_questions.yaml), which was hand-copied from the GSS codebook. Options marked *(volunteered)* are never read aloud in the real interview - interviewers record them only when a respondent insists - and the panel's prompts treat them the same way.

### Contested social issues

**`abany`** - “Please tell me whether or not you think it should be possible for a pregnant woman to obtain a legal abortion if the woman wants it for any reason?”

> Yes · No

**`cappun`** - “Do you favor or oppose the death penalty for persons convicted of murder?”

> Favor · Oppose

**`grass`** - “Do you think the use of marijuana should be made legal or not?”

> Should be legal · Should not be legal

**`gunlaw`** - “Would you favor or oppose a law which would require a person to obtain a police permit before he or she could buy a gun?”

> Favor · Oppose

**`homosex`** - “What about sexual relations between two adults of the same sex - do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all?”

> Always wrong · Almost always wrong · Wrong only sometimes · Not wrong at all

**`prayer`** - “The United States Supreme Court has ruled that no state or local government may require the reading of the Lord's Prayer or Bible verses in public schools. What are your views on this - do you approve or disapprove of the court ruling?”

> Approve · Disapprove

**`fepol`** - “Do you agree or disagree with this statement: Most men are better suited emotionally for politics than are most women.”

> Agree · Disagree

**`courts`** - “In general, do you think the courts in this area deal too harshly or not harshly enough with criminals?”

> Too harshly · Not harshly enough · About right *(volunteered)*

### Government spending & role of government

**`natenvir`** - “We are faced with many problems in this country, none of which can be solved easily or inexpensively. I'm going to name one of these problems, and I'd like you to tell me whether you think we're spending too much money on it, too little money, or about the right amount. Improving and protecting the environment - are we spending too much, too little, or about the right amount?”

> Too little · About right · Too much

**`natheal`** - same wording as `natenvir`, for “Improving and protecting the nation's health”

> Too little · About right · Too much

**`natrace`** - same wording as `natenvir`, for “Improving the conditions of Blacks”

> Too little · About right · Too much

**`natfare`** - same wording as `natenvir`, for “Welfare”

> Too little · About right · Too much

**`nataid`** - same wording as `natenvir`, for “Foreign aid”

> Too little · About right · Too much

**`eqwlth`** - “Some people think that the government in Washington ought to reduce the income differences between the rich and the poor, perhaps by raising the taxes of wealthy families or by giving income assistance to the poor. Others think that the government should not concern itself with reducing this income difference between the rich and the poor. Here is a card with a scale from 1 to 7. Think of a score of 1 as meaning that the government ought to reduce the income differences between rich and poor, and a score of 7 meaning that the government should not concern itself with reducing income differences. What score between 1 and 7 comes closest to the way you feel?”

> 1 - Government should reduce income differences · 2 · 3 · 4 · 5 · 6 · 7 - Government should not concern itself with income differences

**`helppoor`** - “Some people think that the government in Washington should do everything possible to improve the standard of living of all poor Americans; they are at Point 1 on this card. Other people think it is not the government's responsibility, and that each person should take care of himself; they are at Point 5. Where would you place yourself on this scale, or haven't you made up your mind on this?”

> 1 - Government should improve living standards · 2 · 3 - Agree with both · 4 · 5 - People should take care of themselves

### Trust in people & institutions

**`trust`** - “Generally speaking, would you say that most people can be trusted or that you can't be too careful in dealing with people?”

> Most people can be trusted · You can't be too careful in dealing with people · Depends *(volunteered)*

**`fair`** - “Do you think most people would try to take advantage of you if they got a chance, or would they try to be fair?”

> Would take advantage of you · Would try to be fair · Depends *(volunteered)*

**`helpful`** - “Would you say that most of the time people try to be helpful, or that they are mostly just looking out for themselves?”

> Try to be helpful · Just look out for themselves · Depends *(volunteered)*

**`conlegis`** - “I am going to name an institution in this country. As far as the people running this institution are concerned, would you say you have a great deal of confidence, only some confidence, or hardly any confidence at all in them? Congress.”

> A great deal · Only some · Hardly any

**`confinan`** - same wording as `conlegis`, for “Banks and financial institutions”

> A great deal · Only some · Hardly any

**`conarmy`** - same wording as `conlegis`, for “The military”

> A great deal · Only some · Hardly any

### Self-assessment & identity

**`happy`** - “Taken all together, how would you say things are these days - would you say that you are very happy, pretty happy, or not too happy?”

> Very happy · Pretty happy · Not too happy

**`health`** - “Would you say your own health, in general, is excellent, good, fair, or poor?”

> Excellent · Good · Fair · Poor

**`satfin`** - “We are interested in how people are getting along financially these days. So far as you and your family are concerned, would you say that you are pretty well satisfied with your present financial situation, more or less satisfied, or not satisfied at all?”

> Pretty well satisfied · More or less satisfied · Not satisfied at all

**`polviews`** - “We hear a lot of talk these days about liberals and conservatives. I'm going to show you a seven-point scale on which the political views that people might hold are arranged from extremely liberal - point 1 - to extremely conservative - point 7. Where would you place yourself on this scale?”

> Extremely liberal · Liberal · Slightly liberal · Moderate, middle of the road · Slightly conservative · Conservative · Extremely conservative

**`partyid`** - “Generally speaking, do you usually think of yourself as a Republican, Democrat, Independent, or what?”

> Strong Democrat · Not very strong Democrat · Independent, close to Democrat · Independent · Independent, close to Republican · Not very strong Republican · Strong Republican · Other party *(volunteered)*
