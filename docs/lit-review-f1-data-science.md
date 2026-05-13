# Literature Review: Formula 1 Data Science

Compiled: 2026-05-11. ~75 sources across academic papers, open-source tools, datasets, and practitioner resources.

---

## 1. Data Infrastructure & APIs

### 1.1 Primary Data Sources

**FastF1** (Oehrly, T., 2019–present)
https://github.com/theOehrly/Fast-F1 | https://docs.fastf1.dev/
The canonical Python library for F1 data. Wraps the official F1 live-timing API, returning lap-by-lap timing, car telemetry (speed, throttle, brake, gear, DRS, RPM, X/Y position), tyre data, weather, and session schedules as Pandas DataFrames. Includes Matplotlib integration and disk caching. ~4k GitHub stars. Used as the primary data backbone in the majority of published F1 research.

**Jolpica-F1 API** (jolpica team, 2024–present)
https://github.com/jolpica/jolpica-f1
Open-source REST API and direct, backwards-compatible successor to the Ergast Motor Racing Database (which shut down end of 2024). Provides historical race results, standings, driver and constructor metadata. Apache 2.0 licensed. FastF1 and f1dataR both migrated to this source.

**OpenF1 API** (br-g, 2023–present)
https://openf1.org/ | https://github.com/br-g/openf1
Open-source REST API with 18 endpoints. Provides real-time and historical F1 telemetry (car location, speed, throttle, brake, RPM, gear at 3.7 Hz), intervals, pit data, team radio, and race control messages. Historical data from 2023 onward is free; real-time updates arrive ~3 seconds behind live broadcast.

**f1dataR** (Casanova, S., active)
https://github.com/SCasanova/f1dataR | https://cran.r-project.org/package=f1dataR
CRAN-published R package wrapping the Jolpica API and FastF1 Python library. Covers lap times (from 1996), driver telemetry, pit stops, and tyre information. Enables native R-based statistical F1 analysis.

**F1DB** (f1db community, active — updated February 2026)
https://github.com/f1db/f1db
Comprehensive structured open-source database of Formula 1 historical data. Useful as a flat-file alternative or supplement to API-based sources.

**TracingInsights** (active)
https://tracinginsights.com/ | https://github.com/TracingInsights-Archive/2025
Public F1 telemetry data archive (2025 season and prior) alongside a web analytics platform. Functions as the practitioner benchmark for production-quality F1 data visualization.

**livef1** (PyPI, active)
https://pypi.org/project/livef1/
Python toolkit for real-time and historical F1 data; positioned as a higher-level alternative to direct OpenF1 API calls. Handles authentication, pagination, and schema differences automatically.

**F1Archive** (Cooney, C.)
https://medium.com/analytics-vidhya/f1archive-a-python-library-for-analsying-f1-data-e40f831633a9
Library wrapping the official Formula1.com data endpoints with simple Python classes. Covers data that FastF1 does not expose.

---

## 2. Race Outcome Prediction

### 2.1 Classical ML Approaches

**"The Use of Machine Learning in Predicting Formula 1 Race Outcomes"** (Preprints.org, April 2025)
https://www.preprints.org/manuscript/202504.1471
Comparative review of logistic regression, decision tree, random forest, SVM, GNB, and KNN for race outcome prediction. Identifies starting grid position as the most influential single feature (coefficient 0.46). XGBoost and Random Forest perform best overall. Not yet peer-reviewed.

**"Applying Machine Learning to Forecast Formula 1 Race Outcomes"** (Aalto University thesis, 2023)
https://aaltodoc.aalto.fi/items/5848c100-478d-45dd-b2e8-5caf3a3114fb
Comprehensive ML framework evaluating logistic regression, random forest, SVM, gradient boosting, and KNN. XGBoost performed best, followed by Random Forest. Establishes baseline benchmarks for classification-based race prediction.

**"A Data-Driven Analysis of Formula 1 Car Races Outcome"** (Patil et al., Springer AICS 2023)
https://link.springer.com/chapter/10.1007/978-3-031-26438-2_11
Applies PCA to 21 race features, reducing to 4 orthogonal dimensions explaining ~70% of captured variance. Encodes track status (yellow flag, safety car) as a categorical feature — one of the few papers treating race flags as an ML input.

**"Hybrid Predictive Modeling for Formula 1 Race Outcomes: Integrating Random Forest and Graph Neural Networks"** (Springer, 2025)
https://link.springer.com/chapter/10.1007/978-981-96-8350-5_15
GridSearch-optimized RF with SMOTE for class imbalance, output fed into a GNN to refine race predictions. Models driver interactions as a graph structure, capturing positional interdependence that standard tabular models miss. First published GNN application to F1 race outcome prediction.

**"Formula 1 Race Winner Prediction Using Random Forest and SHAP Analysis"** (IEEE Xplore, 2024/2025)
https://ieeexplore.ieee.org/document/10932140/
RF classifier with SHAP values to explain which features drive predictions. Provides interpretability beyond black-box accuracy.

**"Advanced Machine Learning Approaches for Formula 1 Race Performance Prediction"** (ResearchGate, 2025)
https://www.researchgate.net/publication/394015807
Uses 589,081 individual lap times across 1,125 races (1950–2024). Gradient boosting achieved R²=0.999 on historical data — near-perfect results warrant caution about overfitting.

**"Predicting Formula 1 Race Outcomes: Decomposing the Roles of Drivers and Constructors through Linear Modeling"** (arXiv:2508.00200, 2025)
https://arxiv.org/abs/2508.00200
Applies Regularized Adjusted Plus Minus (RAPM) with time-decayed ridge regression and LOESS smoothing across the hybrid era (2014–2024). Finds constructors explain 64.0% of variance. Imports the RAPM methodology from basketball analytics.

**"Predicting race results using artificial neural networks"** (Stoppels et al., Semantic Scholar)
https://www.semanticscholar.org/paper/Predicting-race-results-usingartificial-neural-Stoppels/3febdd13c90ec33862aa4f2e1f560c19a6764a9e
One of the earlier deep learning treatments of F1 race result prediction, available with full text on Semantic Scholar.

**"Benchmarking Formula 1 Results Using a Normal Model"** (Fry, J. & Fanzon, S., arXiv:2603.15192, 2026)
https://arxiv.org/abs/2603.15192
Uses univariate and bivariate normal models to set performance benchmarks at driver and team levels, applied to the 2025 season. Distinguishes elite from non-elite teams via statistical hypothesis testing rather than ranking models.

### 2.2 Qualifying & Practice as Predictors

**"Evaluating the Predictive Power of Qualifying Performance in Formula One Grand Prix"** (arXiv:2507.10966, 2025)
https://arxiv.org/abs/2507.10966
Finds qualifying position is the strongest single predictor of race outcome, with Practice 3 (FP3) having the strongest correlation to final race result (Rel Freq = 0.350). Rigorous statistical framework for evaluating grid-position-based predictions.

**"Predicting Qualification Ranking Based on Practice Session Performance"** (AWS ML Blog)
https://aws.amazon.com/blogs/machine-learning/predicting-qualification-ranking-based-on-practice-session-performance-for-formula-1-grand-prix/
Hierarchical Bayesian model with varying intercepts per driver and circuit to predict qualifying rank from practice data. Probabilistic treatment producing uncertainty intervals, not point estimates. Written by F1/AWS data scientists.

---

## 3. Lap Time & Telemetry Analysis

**"Deep Neural Network-Based Lap Time Forecasting of Formula 1 Racing"** (2024)
https://ace.ewapub.com/article/view/10867 | https://www.researchgate.net/publication/379012640
Uses a DNN to predict fastest qualifying lap times per driver per circuit. The network learns each driver's circuit-specific performance characteristics, treating it as a supervised regression problem. Demonstrates DNNs outperform traditional regression for high-dimensional, non-linear F1 performance.

**"Predicting Lap Times in a Formula 1 Race Using Deep Learning Algorithms"** (Tilburg University thesis, ~2023)
https://arno.uvt.nl/show.cgi?fid=180319
Frames lap time prediction as time-series forecasting. Identifies tyre life as the dominant feature since lap times increase monotonically with tyre wear. Evaluates LSTM and multivariate variants; multivariate LSTMs significantly outperform univariate models.

**F1 Telemetry Analysis with Azure Data Explorer (ADX)** (Microsoft Tech Community, 2022)
https://techcommunity.microsoft.com/blog/azuredataexplorer/f1-telemetry-analysis-with-azure-data-explorer-adx/3283911
Industry case study showing time-series telemetry analysis at scale using ADX's Kusto Query Language. Demonstrates that F1's 1.1M data points/second/car architecture maps onto columnar streaming databases. Directly relevant to real-time dashboard architecture.

**"Real-Time Optimal Trajectory Planning for Autonomous Vehicles and Lap Time Simulation Using Machine Learning"** (arXiv:2102.02315, 2021)
https://arxiv.org/abs/2102.02315
Trains a feed-forward neural network to generate racing-line predictions for arbitrary circuits in real time on desktop hardware, using optimal-control-derived racing lines as training targets. Applicable to F1 track analysis and fastest-lap trajectory prediction.

---

## 4. Race Strategy Optimization

### 4.1 Reinforcement Learning Approaches

**"Explainable Reinforcement Learning for Formula One Race Strategy"** (Thomas et al., ACM SAC 2025)
https://arxiv.org/abs/2501.04068 | https://dl.acm.org/doi/abs/10.1145/3672608.3707766
PPO-trained neural policy for pit strategy in collaboration with Mercedes-AMG Petronas. Achieves average finishing position P5.33 vs. P5.63 for the Monte Carlo baseline on the 2023 Bahrain GP. Provides human-interpretable explanations for strategy decisions — significant advantage over black-box approaches.

**"Towards Learning-Based Formula 1 Race Strategies"** (arXiv:2512.21570, December 2025)
https://arxiv.org/abs/2512.21570
Two complementary frameworks for jointly optimizing energy allocation, tyre wear, and pit stop timing using lap time maps and a dynamic tyre wear model. Designed for fast runtime inference to support live human decision-making. One of the most complete recent formulations of the multi-objective F1 strategy problem.

**"Learning-based Multi-agent Race Strategies in Formula 1"** (arXiv:2602.23056, February 2026)
https://arxiv.org/abs/2602.23056
Extends single-agent RL to multi-agent settings where agents balance energy management, tyre degradation, aerodynamic interactions, and pit decisions while accounting for competitors' behavior. Introduces interaction modules modeling rival agents. Current frontier in F1 strategy ML.

**"Optimum Racing: A F1 Strategy Predictor using Reinforcement Learning"** (IJRASET, 2024)
https://www.ijraset.com/research-paper/optimum-racing-a-f1-strategy-predictor-using-reinforcement-learning
Applies PPO and Q-learning in a Streamlit-based simulator to optimize pit stop timing under dynamic conditions including safety car and weather events. Demonstrates RL advantages over hard-coded strategies in non-stationary race dynamics.

**"Mastering Nordschleife: A Comprehensive Race Simulation for AI Strategy Decision-Making"** (Boettinger et al., arXiv:2306.16088, 2023)
https://arxiv.org/abs/2306.16088
Builds a GT-race simulation environment parametrised on F1 regulations (2014–2019), integrated with OpenAI Gym for RL. Neural networks trained on historic race data automate pit-stop strategy decisions and replace manual in-lap estimation.

**"Opponent State Inference Under Partial Observability: An HMM-POMDP Framework for 2026 Formula 1 Energy Strategy"** (Kleisarchaki, arXiv:2603.01290, March 2026)
https://arxiv.org/abs/2603.01290
Addresses the 2026 50/50 ICE/battery split and Override Mode via a 30-state HMM that infers rivals' ERS charge from five observable telemetry signals. A DQN policy uses the HMM belief state to select energy deployment strategies. Represents the most forward-looking energy strategy paper.

### 4.2 Game-Theoretic Approaches

**"Game Theory in Formula 1: From Physical to Strategic Interactions"** (Fieni et al., arXiv:2503.05421, March 2025)
https://arxiv.org/abs/2503.05421
Formulates the two-car minimum-lap-time problem as Nash or Stackelberg games, reformulated as single-level NLP via KKT conditions. Integrates aerodynamic wake, trajectory optimization, and energy management to identify optimal overtaking locations.

**"Game-theoretic Energy Management Strategies With Interacting Agents in Formula 1"** (Fieni et al., arXiv:2405.11032, 2024)
https://arxiv.org/abs/2405.11032
Interaction-aware energy management framework where two F1 agents play a Stackelberg bilevel game capturing DRS interactions. Yields new energy deployment strategies accounting for rival presence.

**"Optimizing Pit Stop Strategies with Competition in a Zero-Sum Feedback Stackelberg Game"** (Aguad & Thraves, EJOR 2024)
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4470115 | https://ideas.repec.org/a/eee/ejores/v319y2024i3p908-919.html
Published in European Journal of Operational Research (319:3, 908–919). Game-theoretic framing of pit strategy as Stackelberg competition; models inter-team strategic dependencies. Rare formal game-theory treatment in F1 distinct from simulation and ML approaches.

### 4.3 Simulation-Based Approaches

**"Application of Monte Carlo Methods in Circuit Motorsport"** (TUMFTM, MDPI Applied Sciences 2020)
https://www.mdpi.com/2076-3417/10/12/4229
Academic paper behind the TUMFTM race simulator. Formalises probabilistic modelling of safety car phases, tyre failures, and pit stop variance. The reference methodology for rigorous strategy simulation in motorsport.

**"Monte Carlo, Game Theory, Machine Learning: The Race Strategy Triangle"** (Sigma Machine Learning Blog)
https://www.sigmachinelearning.com/post/monte-carlo-game-theory-machine-learning-the-race-strategy-triangle-for-formula-1
Conceptual piece framing F1 strategy as three interlocking layers: Monte Carlo for scenario enumeration, game theory for opponent modelling, ML for parameter estimation. Useful mental model for strategy system design.

---

## 5. Tyre Degradation Modeling

**"Explainable Time Series Prediction of Tyre Energy in Formula One Race Strategy"** (Todd et al., ACM SAC 2025)
https://arxiv.org/abs/2501.04067 | https://dl.acm.org/doi/10.1145/3672608.3707765
Uses Mercedes-AMG Petronas telemetry to train deep learning and XGBoost models to forecast per-tyre energy during races. Tyre energy is the primary driver of degradation rate. Applies SHAP-based explainability so strategists can interrogate predictions. CausalImpact used to quantify VSC effects on tyre energy. First reported use of AI for tyre energy prediction in F1.

**"A State-Space Approach to Modeling Tire Degradation in Formula 1 Racing"** (arXiv:2512.00640, November 2025)
https://arxiv.org/abs/2512.00640
Proposes a Bayesian state-space framework where tyre degradation is a latent process inferred from observed lap times via FastF1. Provides probabilistic degradation estimates and interpretable lap time predictions suitable for runtime strategy use. Fully reproducible on public data.

**"Formula 1 Tyre Analytics with Python"** (Chortarias, D., 2023)
https://dimitris-chortarias.medium.com/formula-1-tyre-analytics-with-python-5514c4d12d8a
Practitioner tutorial on reconstructing team strategies from lap data, analyzing tyre compound distribution, and visualizing degradation rates. Uses FastF1 exclusively; covers the core tyre analytics workflow used in post-race analysis.

---

## 6. Pit Stop Decision Support

**"Data-Driven Pit Stop Decision Support for Formula 1 Using Deep Learning Models"** (Frontiers in AI, 2025)
https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1673148/full | https://pmc.ncbi.nlm.nih.gov/articles/PMC12626961/
Evaluates five deep learning architectures (Bi-LSTM, TCN-GRU, GRU, InceptionTime, CNN-BiLSTM) on FastF1 telemetry from 2020–2024. Bi-LSTM achieved precision 0.77, recall 0.86, F1-score 0.81. Game-theoretic extension yields ~2.3 s average race time improvement. Models handle safety car and wet weather events. Open-access, fully replicable.

**"From Data to Podium: A Machine Learning Model for Predicting Formula 1 Pit Stop Timing"** (Universidade Nova de Lisboa thesis, 2024)
https://run.unl.pt/bitstream/10362/175111/1/FROM_DATA_TO_PODIUM_A_MACHINE_LEARNING_MODEL_FOR_PREDICTING_FORMULA_1_PIT_STOP_TIMING.pdf
Probabilistic ML model using race data from 2018–2023 outputting per-lap pit stop probability. Designed as decision-support for strategists. Frames pit stop prediction as a classification problem.

---

## 7. Driver Skill & Performance Rating

### 7.1 Statistical / Bayesian Rating

**"Bayesian Analysis of Formula One Race Results: Disentangling Driver Skill and Constructor Advantage"** (van Kesteren & Bergkamp, JQAS 2023)
https://arxiv.org/abs/2203.08489 | https://www.degruyterbrill.com/document/doi/10.1515/jqas-2022-0021/html
The most-cited recent academic paper on F1 driver rating. Bayesian multilevel rank-ordered logit regression over the hybrid era (2014–2021). Key finding: ~88% of variance in race results is explained by the constructor. Hamilton and Verstappen top the driver ranking. Full replication data at Zenodo.

**"Formula for Success: Multilevel Modelling of Formula One Driver and Constructor Performance, 1950–2014"** (Bell et al., JQAS 2016)
https://www.degruyterbrill.com/document/doi/10.1515/jqas-2015-0050/html
Cross-classified multilevel random-coefficient models rank all-time drivers (Fangio first), partition variance into team/team-year/driver levels. Shows team effects have grown over time but driver effects matter more in wet conditions and on street circuits. The seminal long-horizon driver study.

**"Uncovering Formula One Driver Performances from 1950 to 2013 by Adjusting for Team and Competition Effects"** (Eichenberger & Stadelmann, JQAS 2014)
https://www.degruyterbrill.com/document/doi/10.1515/jqas-2013-0031/html
Statistical decomposition model isolating pure driver contribution from team quality and field strength. All-time top five: Clark, Stewart, Fangio, Alonso, Schumacher. Methodologically distinct from Bell et al. in using competition-adjustment rather than multilevel framing.

**"Faster Identification of Faster Formula 1 Drivers via Time-Rank Duality"** (arXiv:2312.14637, 2023)
https://arxiv.org/html/2312.14637
Derives a time-rank duality showing exponential-time and rank-based race models are mathematically equivalent, enabling faster statistical identification of driver skill differences from fewer races. Theoretical contribution with practical implications for mid-season driver rating updates.

### 7.2 Elo-Based Rating

**"Adjusting Elo Method to Separate Car and Driver in Formula 1"** (SIAM preprint)
https://www.siam.org/media/ze4lf1m2/s152289rrr.pdf
Modifies classic Elo win-probability to include a car-year rating term alongside driver rating. Provides paired (driver, car) estimates updated race-by-race. Simpler online-update approach complementing Bayesian methods.

**"Formula 1 Driver Comparison by Elo and Plots"** (Matus, R., Santa Clara University)
https://www.ryanmatus.com/doc/MatusF1Comparison.pdf
Applies round-robin Elo treating each race as a series of pairwise matchups. Produces three separate scores: Qualifying Elo, Race Elo, Global Elo (30/70 weighted). Useful baseline methodology for driver comparison.

**"Score-Driven Rating System for Sports"** (Holý & Černý, arXiv:2604.09143, April 2026)
https://arxiv.org/abs/2604.09143
Generalises the Elo rating system via score-driven (GAS) updating, accommodating ranking outcomes including F1 championship standings. Derives theoretical properties; applied to time-varying player/team strength estimation.

---

## 8. Overtaking, Regulations & Competitive Balance

**"Overtaking in Formula 1 During the Pirelli Era: A Driver-Level Analysis"** (de Groote, J., JSA 2021)
https://journals.sagepub.com/doi/10.3233/JSA-200466
Poisson regression on individual-level overtaking data (2011–2018). Attributes 50% of overtaking decline to car aerodynamics, 20–30% to smaller field sizes, ~20% to more uniform strategies. Key empirical paper on DRS effectiveness.

**"Aerodynamics, Technology or Pit Strategy: Why Did Overtaking in Formula 1 Decline During the 1980s and 1990s?"** (de Groote, J., JQAS 2025)
https://www.degruyterbrill.com/document/doi/10.1515/jqas-2022-0018/html
Negative-binomial regression on driver-level overtaking data (1983–2010). Separates car aerodynamic effects from quantifiable factors (field size, pit strategy adoption). Historical baseline for aerodynamic influence on racing action.

**"Statistical Analysis of the Impact of FIA Regulations on Safety, Racing Dynamics, and Spectacle"** (Belgaid, A., arXiv:2410.11375, 2024)
https://arxiv.org/abs/2410.11375
Analyzes F1 data from 1990–2023 covering fatalities, overtaking statistics, car weights, and regulation changes. Assesses whether FIA regulations improved safety while degrading spectacle. Regulatory-impact quantification grounded in empirical data.

**"Competitiveness of Formula 1 Championship from 2012 to 2022 as Measured by Kendall Corrected Evolutive Coefficient"** (arXiv:2501.00126, January 2025)
https://arxiv.org/abs/2501.00126
Applies a competitive balance metric to F1 Constructors Championship standings 2012–2022. Quantifies how much season-to-season competitive balance has varied across the turbo-hybrid era.

**"A Comparative Study of Scoring Systems by Simulations"** (Csató, L., arXiv:2101.05744, 2021)
https://arxiv.org/abs/2101.05744
Compares four historical F1 World Championship points systems against geometric scoring rules using Monte Carlo simulation. Studies the tradeoff between early title clinch risk and possibility of a champion who never won a race.

**"F1 Versus Indy: Analyzing a Unique Shared-Course Natural Experiment"** (Potter et al., American Behavioral Scientist, 2025)
https://journals.sagepub.com/doi/10.1177/00027642251366044
Uses Indianapolis Motor Speedway as a natural experiment where both series race the same circuit to isolate format-level speed differences. Rare causal identification strategy in motorsport research.

---

## 9. Aerodynamics & Physics

**"Computational Fluid Dynamics Optimization of F1 Front Wing Using Physics Informed Neural Networks"** (Shah, N., arXiv:2509.01963, September 2025)
https://arxiv.org/abs/2509.01963
PINN combining SimScale CFD data with Navier-Stokes constraints for fast prediction of F1 front-wing drag and lift coefficients (R²=0.968/0.981). Motivated by FIA wind tunnel hour restrictions and $135M budget caps — regulatory pressure driving ML adoption in aerodynamics.

---

## 10. Autonomous Racing & Trajectory Optimization

**"Formula RL: Deep Reinforcement Learning for Autonomous Racing using Telemetry Data"** (Remonda et al., arXiv:2104.11106, 2021)
https://arxiv.org/abs/2104.11106
Frames autonomous racing as continuous-action RL with multidimensional vehicle telemetry as input. Studies 10 DDPG variants for lap-time minimisation; tests generalisation to unseen tracks.

**"A Simulation Benchmark for Autonomous Racing with Large-Scale Human Data"** (Remonda et al., arXiv:2407.16680, NeurIPS 2024)
https://arxiv.org/abs/2407.16680
Assetto Corsa-based simulation platform with high-fidelity physics for benchmarking autonomous racing algorithms. Releases a large-scale dataset of human driver laps; evaluates offline RL algorithms against human baselines.

**"Efficient Trajectory Optimization for Autonomous Racing via Formula-1 Data-Driven Initialization"** (Shehadeh et al., Univ. of Bonn, arXiv:2603.07126, March 2026)
https://arxiv.org/abs/2603.07126
Uses reconstructed GPS telemetry from 17 F1 circuits to train a geometric raceline predictor. This prediction seeds trajectory optimizers in place of heuristic centerlines, improving convergence speed and solution quality.

**"Disturbance-aware Minimum-Time Planning Strategies for Motorsport Vehicles with Probabilistic Safety Certificates"** (Gulisano et al., arXiv:2506.13622, June 2025)
https://arxiv.org/abs/2506.13622
Embeds robustness into minimum-lap-time trajectory optimization via open-loop and closed-loop covariance formulations. Both satisfy prescribed safety probabilities; closed-loop variant incurs smaller lap-time penalties.

**"Accelerating Autonomy: Insights from Pro Racers in the Era of Autonomous Racing"** (Werner et al., arXiv:2405.02620, May 2024)
https://arxiv.org/abs/2405.02620
Qualitative study with 11 professional drivers, analysts, and instructors. Uses Mayring's content analysis to categorise expert strategies for approaching vehicle limits, then contrasts them with gaps in current autonomous racing software stacks.

**"Competitor-aware Race Management for Electric Endurance Racing"** (de Vries et al., arXiv:2603.28286, March 2026)
https://arxiv.org/abs/2603.28286
Bi-level framework for electric endurance racing: lower-level multi-agent game-theoretic optimal control captures aerodynamics and collision-avoidance; upper-level RL handles energy and charging strategy. Directly related to F1-style energy constraint problems.

---

## 11. Real-Time Processing & Industry Systems

**"F1 Insights Powered by AWS"** (Amazon Web Services, 2018–present)
https://aws.amazon.com/sports/f1/
AWS has been Official Cloud and ML Provider of F1 since 2018. Infrastructure processes 1.1M data points/second/car (~500 TB per event) over dual 10 Gbps fiber. Produces 20 on-broadcast ML-powered insights including Battle Forecast (overtaking time-to-strike) and Predicted Pit Stop Strategy. Demonstrates production-scale real-time ML on F1 telemetry.

**"How Formula 1 Uses Generative AI to Accelerate Race-Day Issue Resolution"** (AWS ML Blog, 2024)
https://aws.amazon.com/blogs/machine-learning/how-formula-1-uses-generative-ai-to-accelerate-race-day-issue-resolution/
Documents F1's root cause analysis (RCA) system built on Amazon Bedrock (LLM-based) that resolves technical issues up to 86% faster and predicts problems before they arise. Current state of generative AI applied to live motorsport operations.

---

## 12. Computer Vision & NLP Applications

**"f1-racing-cars-tracking"** (Gasparini, A., GitHub)
https://github.com/andrea-gasparini/f1-racing-cars-tracking
Faster R-CNN model for F1 car detection and tracking via transfer learning + histogram distance. Achieves 97% precision / 99% recall for car detection from broadcast footage.

**"Decoding the Grid: Teaching AI to See Formula 1"** (Sobral, V.V., Medium)
https://medium.com/@VforVitorio/decoding-the-grid-teaching-ai-to-see-formula-1-5c3018011811
Walkthrough of training a YOLO model to detect and classify F1 cars by team livery from broadcast footage. Practical computer vision pipeline for livery recognition.

**"Sentiment Analysis of Collected F1 Tweets"** (Parija, P., Medium)
https://medium.com/social-media-theories-ethics-and-analytics/sentiment-analysis-of-collected-f1-tweets-e694db5f9a3a
VADER/TextBlob sentiment analysis on F1 tweets. Entry-level NLP application to F1 fan discourse; demonstrates social media signal extraction from motorsport content.

---

## 13. Open-Source Tools & GitHub Ecosystem

**TUMFTM Race Simulation** (TU Munich, 2020, ~500 stars)
https://github.com/TUMFTM/race-simulation
Academic-grade pit-stop strategy simulator covering 121 F1 races from 2014–2019. Full Python, open-source, covers tyre compound selection and stint modelling. Accompanies the MDPI Monte Carlo paper.

**F1-TELEMETRY-DASHBOARD** (Harmitx7)
https://github.com/Harmitx7/F1-TELEMETRY-DASHBOARD
Web dashboard (Python + Dash + Plotly + Pandas) for uploading, comparing, and visualising F1 telemetry: speed, throttle, brake, RPM, sector times. F1-themed dark UI. Reference implementation for a widget-based telemetry layer.

**pit-stop-simulator** (rembertdesigns)
https://github.com/rembertdesigns/pit-stop-simulator
RL-based (PPO + Q-learning) pit-stop strategy agent with a Streamlit UI. Shows how RL framing differs from simulation and supervised approaches.

**F1_Pitstop_Predict_ML** (laurence9899)
https://github.com/laurence9899/F1_Pitstop_Predict_ML
TensorFlow model producing per-driver, per-lap pit stop probability using 2018–2023 race data. Open-source reference implementation comparable to the Frontiers in AI deep learning paper.

**F1-predictor** (Kalkman, P.)
https://github.com/PatrickKalkman/F1-predictor
PyTorch deep neural network for race outcome prediction; companion code to a practitioner Medium article. Demonstrates the full DL training pipeline on Ergast historical data.

**Race-Strategy-Analysis** (Webster, T.)
https://github.com/TomWebster98/Race-Strategy-Analysis
Scripts for lap-time and race-strategy analysis with narrative "What made the difference?" race reports. Good template for combining structured data analysis with text generation.

**FormulaGPT** (Maj, D.)
https://github.com/dawid-maj/FormulaGPT
LLM-backed race simulator where GPT/Claude/DeepSeek act as team strategists making pit stop and tyre decisions in natural language. Close conceptual cousin to F1Dash's agentic chat architecture.

**fastf1-mcp** (Kunk, A.)
https://github.com/aashnakunk/fastf1-mcp
MCP server exposing 17 FastF1 analysis tools as callable endpoints for LLM agents. Directly relevant as a tool-provider pattern for agentic F1 analysis systems.

**jupyterlite-fastf1** (f1datajunkie)
https://github.com/f1datajunkie/jupyterlite-fastf1
Template for running FastF1 inside a browser-based JupyterLite environment. Enables shareable, zero-install F1 analysis notebooks.

---

## 14. Practitioner Tutorials & Blogs

**"FastF1 Playbook: 10 Notebooks to Master Formula 1 Data in 2026"** (García, R., Medium, 2026)
https://medium.com/formula-one-forever/fastf1-playbook-10-notebooks-to-master-formula-1-data-in-2026-23c347a462b3
The most up-to-date practical reference for FastF1. Ten worked Jupyter notebooks spanning lap time analysis, telemetry comparison, tyre strategy reconstruction, and track map rendering.

**"Towards Formula 1 Analysis" (series)** (Medium publication)
https://medium.com/towards-formula-1-analysis/how-to-analyze-formula-1-data-with-python-a-beginners-tutorial-23087c4eef1d
Multi-part tutorial series covering FastF1 setup, lap comparison, minisector analysis, and championship visualization. The de facto beginner curriculum for Python F1 data analysis.

**"Telemetry Analysis for F1 Enthusiasts" (series, Chapters I–IV)** (García, R., Medium)
https://medium.com/@raulgarciamx/telemetry-analysis-for-f1-enthusiasts-chapter-i-introduction-f91ac2600c16
Chapter-by-chapter series on telemetry signal processing. Covers speed traces, throttle, brake, gear overlaid on lap time comparisons, and graphical telemetry overlays across drivers.

**"Simulating 20,000 F1 Races to Find the Winner Using Monte Carlo Simulation"** (García, R., Python in Plain English)
https://python.plainenglish.io/simulating-20-000-f1-races-to-find-the-winner-using-monte-carlo-simulation-in-python-a3ba181393ba
Python implementation of Monte Carlo race prediction using FastF1-sourced performance distributions. Accessible tutorial connecting probabilistic simulation to real telemetry data.

**"Formula 1 Telemetry Analysis in Python and Tableau"** (Wade, D., The Data School, 2023)
https://www.thedataschool.co.uk/dan-wade/formula-1-telemetry-analysis-in-python-and-tableau/
Combines FastF1 (data extraction) with Tableau (interactive visualization). Covers braking point analysis, corner apex comparison, and driver benchmarking. Reference for BI tooling integrated with F1 telemetry pipelines.

---

## 15. Datasets & Competition Platforms

**"Formula 1 World Championship (1950–2024)"** (Vopani/Rohan Rao, Kaggle)
https://www.kaggle.com/datasets/rohanrao/formula-1-world-championship-1950-2020
The canonical F1 Kaggle dataset — 13 CSV files covering results, qualifying, pit stops, lap times, circuits, drivers, constructors. Most published ML papers use a derivative of this dataset. Updated annually.

**F1nalyze Datathon** (IEEE CS MUJ, Kaggle)
https://www.kaggle.com/competitions/f1nalyze-datathon-ieeecsmuj
Formal academic-style F1 prediction competition. Provides evaluation leaderboard, baseline notebooks, and community solutions. Useful for benchmarking against published ML approaches.

**"F1 Strategy Dataset — Pit Stop Prediction"** (Gupta, A., Kaggle)
https://www.kaggle.com/datasets/aadigupta1601/f1-strategy-dataset-pit-stop-prediction
Lap-level, multi-race dataset preprocessed specifically for pit stop timing classification. Reduces significant feature-engineering overhead for strategy-focused models.

---

## 16. Sponsorship & Commercial Analysis

**"Analyzing Brand Strategy on an International Scale: The Sponsorship Performance Cycle in Formula One Racing"** (Jensen et al., Journal of International Marketing, 2024)
https://journals.sagepub.com/doi/10.1177/1069031X241255094
Examines how multinational firms leverage F1 sponsorships. Introduces a "Sponsorship Performance Cycle" framework. Represents the commercial data dimension often ignored in pure performance analytics.

---

## Summary Statistics

| Category | Sources |
|---|---|
| APIs & Data Infrastructure | 8 |
| Race Outcome Prediction | 10 |
| Lap Time & Telemetry | 4 |
| Race Strategy (RL + Game Theory + Simulation) | 11 |
| Tyre Degradation | 3 |
| Pit Stop Decision Support | 2 |
| Driver Rating & Skill Analysis | 7 |
| Overtaking, Regulations & Competitive Balance | 6 |
| Aerodynamics & Physics | 1 |
| Autonomous Racing & Trajectory | 5 |
| Real-Time & Industry Systems | 2 |
| Computer Vision & NLP | 3 |
| Open-Source Tools & GitHub | 11 |
| Practitioner Tutorials | 5 |
| Datasets | 3 |
| Sponsorship & Commercial | 1 |
| **Total** | **~82** |

---

## Key Gaps & Open Problems (as of May 2026)

1. **Live agentic analysis**: No published work combines a real-time LLM agent with live telemetry APIs (OpenF1) to answer natural-language F1 questions — the space F1Dash occupies.
2. **Multi-modal F1 AI**: Computer vision (car tracking, livery detection) has not been integrated with statistical performance models.
3. **Social signal integration**: NLP on team radio, fan tweets, and commentary as input features for performance or strategy models is largely unexplored.
4. **2026 regulations**: The 50/50 power unit rule creates an entirely new energy strategy landscape; only one paper (arXiv:2603.01290) addresses it.
5. **Cross-championship transfer**: Whether models trained on one season generalize across regulation eras is rarely studied rigorously.

---

*Assumptions: Author lists for several Springer/IEEE/arXiv entries are incomplete where search results did not surface full author rosters. Publication years inferred from arXiv ID prefixes and search metadata. URLs retrieved from web search; full-text access and paywall status not verified for every source. No direct API access to Semantic Scholar or IEEE Xplore was used.*
