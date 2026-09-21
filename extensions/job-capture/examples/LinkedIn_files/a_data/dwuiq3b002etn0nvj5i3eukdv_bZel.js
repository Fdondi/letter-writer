define("@ember/test-waiters/build-waiter",["exports","@babel/runtime/helpers/esm/defineProperty","@ember/debug","@ember/test-waiters/token","@ember/test-waiters/waiter-manager"],(function(e,t,n,i,o){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e._resetWaiterNames=function(){r=new Set}
e.default=function(e){0
return new a(e)}
let r
class a{constructor(e){this.name=e}beginAsync(){return this}endAsync(){}waitUntil(){return!0}debugInfo(){return[]}reset(){}}}))
define("@ember/test-waiters/index",["exports","@ember/test-waiters/waiter-manager","@ember/test-waiters/build-waiter","@ember/test-waiters/wait-for-promise","@ember/test-waiters/wait-for"],(function(e,t,n,i,o){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
Object.defineProperty(e,"_reset",{enumerable:!0,get:function(){return t._reset}})
Object.defineProperty(e,"_resetWaiterNames",{enumerable:!0,get:function(){return n._resetWaiterNames}})
Object.defineProperty(e,"buildWaiter",{enumerable:!0,get:function(){return n.default}})
Object.defineProperty(e,"getPendingWaiterState",{enumerable:!0,get:function(){return t.getPendingWaiterState}})
Object.defineProperty(e,"getWaiters",{enumerable:!0,get:function(){return t.getWaiters}})
Object.defineProperty(e,"hasPendingWaiters",{enumerable:!0,get:function(){return t.hasPendingWaiters}})
Object.defineProperty(e,"register",{enumerable:!0,get:function(){return t.register}})
Object.defineProperty(e,"unregister",{enumerable:!0,get:function(){return t.unregister}})
Object.defineProperty(e,"waitFor",{enumerable:!0,get:function(){return o.default}})
Object.defineProperty(e,"waitForPromise",{enumerable:!0,get:function(){return i.default}})}))
define("@ember/test-waiters/token",["exports"],(function(e){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=class{}}))
define("@ember/test-waiters/types/index",["exports"],(function(e){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})}))
define("@ember/test-waiters/wait-for-promise",["exports","@ember/test-waiters/build-waiter"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=function(e,t){let n=e
0
return n};(0,t.default)("@ember/test-waiters:promise-waiter")}))
define("@ember/test-waiters/wait-for",["exports","@ember/test-waiters/wait-for-promise","@ember/test-waiters/build-waiter"],(function(e,t,n){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=function(){for(var e=arguments.length,t=new Array(e),n=0;n<e;n++)t[n]=arguments[n]
if(t.length<3){let[e,n]=t
return i(e,n)}{let[,,e,n]=t
return e}}
function i(e,t){return e}(0,n.default)("@ember/test-waiters:generator-waiter")}))
define("@ember/test-waiters/waiter-manager",["exports","ember","@ember/test"],(function(e,t,n){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e._reset=function(){for(let e of r())e.isRegistered=!1
i.clear()}
e.getPendingWaiterState=a
e.getWaiters=r
e.hasPendingWaiters=l
e.register=function(e){i.set(e.name,e)}
e.unregister=function(e){i.delete(e.name)}
const i=function(){let e="TEST_WAITERS",t="undefined"!=typeof Symbol?Symbol.for(e):e,n=o(),i=n[t]
void 0===i&&(i=n[t]=new Map)
return i}()
function o(){if("undefined"!=typeof globalThis)return globalThis
if("undefined"!=typeof self)return self
if("undefined"!=typeof window)return window
if("undefined"!=typeof global)return global
throw new Error("unable to locate global object")}t.default.Test&&(0,n.registerWaiter)((()=>!l()))
function r(){let e=[]
i.forEach((t=>{e.push(t)}))
return e}function a(){let e={pending:0,waiters:{}}
i.forEach((t=>{if(!t.waitUntil()){e.pending++
let n=t.debugInfo()
e.waiters[t.name]=n||!0}}))
return e}function l(){return a().pending>0}}))
define("@embroider/macros/es-compat",["exports"],(function(e){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=function(e){return null!=e&&e.__esModule?e:{default:e}}}))
define("@embroider/macros/runtime",["exports"],(function(e){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.config=t
e.each=function(e){if(!Array.isArray(e))throw new Error("the argument to the each() macro must be an array")
return e}
e.getGlobalConfig=n
e.isTesting=function(){let e=i.global,t=e&&e["@embroider/macros"]
return Boolean(t&&t.isTesting)}
e.macroCondition=function(e){return e}
function t(e){return i.packages[e]}function n(){return i.global}const i={packages:{},global:{}}
let o="undefined"!=typeof window?window._embroider_macros_runtime_config:void 0
if(o){let e={config:t,getGlobalConfig:n,setConfig(e,t){i.packages[e]=t},setGlobalConfig(e,t){i.global[e]=t}}
for(let t of o)t(e)}}))
define("@glimmer/component/-private/base-component-manager",["exports","@babel/runtime/helpers/esm/defineProperty","@glimmer/component/-private/component"],(function(e,t,n){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=function(e,n,i){return class{static create(e){return new this(n(e))}constructor(n){(0,t.default)(this,"capabilities",i)
e(this,n)}createComponent(e,t){0
return new e(n(this),t.named)}getContext(e){return e}}}}))
define("@glimmer/component/-private/component",["exports","@babel/runtime/helpers/esm/defineProperty","@glimmer/component/-private/owner","@glimmer/component/-private/destroyables"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=e.ARGS_SET=void 0
e.ARGS_SET=void 0
0
e.default=class{constructor(e,i){(0,t.default)(this,"args",void 0)
0
this.args=i;(0,n.setOwner)(this,e)}get isDestroying(){return(0,i.isDestroying)(this)}get isDestroyed(){return(0,i.isDestroyed)(this)}willDestroy(){}}}))
define("@glimmer/component/-private/destroyables",["exports","ember"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.isDestroying=e.isDestroyed=void 0
e.isDestroying=t.default._isDestroying,e.isDestroyed=t.default._isDestroyed}))
define("@glimmer/component/-private/ember-component-manager",["exports","ember","@ember/object","@ember/application","@ember/component","@ember/runloop","@glimmer/component/-private/base-component-manager","@glimmer/component/-private/destroyables"],(function(e,t,n,i,o,r,a,l){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
const{setDestroyed:s,setDestroying:c}=l,u=(0,o.capabilities)("3.13",{destructor:!0,asyncLifecycleCallbacks:!1,updateHook:!1}),d=t.default.destroy,m=t.default._registerDestructor
class p extends((0,a.default)(i.setOwner,i.getOwner,u)){createComponent(e,t){const n=super.createComponent(e,t)
m(n,(()=>{n.willDestroy()}))
return n}destroyComponent(e){d(e)}}0
e.default=p}))
define("@glimmer/component/-private/owner",["exports","@ember/application"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
Object.defineProperty(e,"setOwner",{enumerable:!0,get:function(){return t.setOwner}})}))
define("@glimmer/component/index",["exports","@ember/component","@glimmer/component/-private/ember-component-manager","@glimmer/component/-private/component"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
let o=i.default
0;(0,t.setComponentManager)((e=>new n.default(e)),o)
e.default=o}))
define("@linkedin/ember-stdlib/utils/environment",["exports","@ember/debug","@linkedin/ember-stdlib/utils/is-browser"],(function(e,t,n){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default={isBrowser:function(){return n.default}}}))
define("@linkedin/ember-stdlib/utils/is-browser",["exports"],(function(e){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
const t="undefined"!=typeof window&&window&&"node"!==window.appEnvironment
e.default=t}))
define("artdeco-icons-web/components/linkedin-logo",["exports","@ember/component","@ember/object","@ember/object/evented","artdeco-icons-web/templates/components/linkedin-logo"],(function(e,t,n,i,o){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
const r={iconType:{msg:'The linkedin-logo requires the type attribute be suffixed with either "-bug" or "-logo" corresponding to the icon type.',values:["linkedin-bug","linkedin-logo"]},iconVariant:{msg:"The type attribute on linkedin-logo is prefixed with an unsupported variant. Please add a variant based on the supported icon colors.",values:["","premium","brand","inverse"]},size:{msg:'The linkedin-logo requires an attribute of "size" with a value corresponding to a supported icon size. Supported sizes are 14dp, 21dp, 28dp, 34dp, 40dp and 48dp',values:["14dp","21dp","28dp","34dp","40dp","48dp"]},color:{msg:'The linkedin-logo expects to color attribute to be null, "dark", or "inverse"',values:["dark","inverse"]},type:{msg:'The linkedin-logo requires an attribute of "type".'}}
e.default=t.default.extend({layout:o.default,tagName:"linkedin-logo",attributeBindings:["size"],classNameBindings:["vertical"],size:null,type:null,color:"",vertical:!1,init(){this._super(...arguments)
this._validateProps(["size","type"],!0)
this._validateProps(["size"])
this.get("color")&&this._validateProps(["color"])},colorClassname:(0,n.computed)("color",(function(){const e=this.get("color")
return e?`logo-lockup-${e}`:null})),setIconProperties:(0,i.on)("init",(0,n.observer)("type",(function(){const e=this.get("type").split("-"),t=e.length>1?e[0]:""
let n=e.length>1?e[1]:e[0]
n=`linkedin-${n}`
this.set("iconVariant",t)
this.set("iconType",n)
this._validateProps(["iconVariant","iconType"])}))),validateVerticalLockup:(0,i.on)("init",(0,n.observer)("size","vertical",(function(){const e=this.get("vertical"),t=this.get("size")
if(e&&!("40dp"===t||"48dp"===t))throw new Error("The vertical linkedin-logo is only available in sizes 40dp and 48dp.")}))),_validateProps(e,t){const n=this
e.forEach((e=>{const i=n.get(e),o=r[e]
if(t){if(!i)throw new Error(o.msg)}else if(-1===o.values.indexOf(i))throw new Error(o.msg)}))}})}))
define("artdeco-icons-web/helpers/li-icon",["exports","@ember/component/helper","@ember/debug","artdeco-icons-web/src/icons","artdeco-icons-web/src/li-icon"],(function(e,t,n,i,o){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
function r(e,t){o.default.setIcon(e,t.type,t.size,!!t.color,t.active)}e.default=(0,t.helper)((function(e,t){0
if(!o.default)return""
const n=o.default.create(t)
!function(e,t){if(i.default.isLoaded())r(e,t)
else{i.default.load().then((()=>{e.removeAttribute("is-loading")
r(e,t)}))
e.setAttribute("is-loading","true")}}(n,t)
const a=t["a11y-text"]||t.a11yText
o.default.setA11yText(n,a)
return n}))}))
define("artdeco-icons-web/src/convert-icon-name",["exports","artdeco-icons-web/src/icon-conversion-utils"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=function(e,r,a,l){const s=function(e){let t=arguments.length>1&&void 0!==arguments[1]?arguments[1]:"large",n=arguments.length>2?arguments[2]:void 0,i=arguments.length>3?arguments[3]:void 0,o=e
n&&(o=`${o}-color`)
i&&(o=`${o}-active`)
return`${o}-${t}`}(e,r,a,l),c=o[s]
if(c)return{newType:c.name,category:c.category}
const u=function(e){if(0===e.indexOf("nav-"))return"nav"
if(0===e.indexOf("app-"))return"app"
if(i[e]||e.includes("premium-wordmark")||e.includes("premium-badge")||e.includes("linkedin-bug")&&e.includes("on-dark"))return"scaling"
if(n[e])return"social"
return"ui"}(e)
let d=e
switch(u){case"ui":d=(0,t.handleUIIcons)(e,r)
break
case"social":d=(0,t.handleSocialIcons)(e,a)
break
case"app":d=(0,t.handleAppIcons)(e)
break
case"nav":d=(0,t.handleNavIcons)(e,r,l)
break
case"scaling":r&&(d=(0,t.handleScalingIcons)(e,r))}o[s]={name:d,category:u}
return{newType:d,category:u}}
const n={"adchoices-icon":1,"amp-icon":1,"aol-icon":1,"aol-mail-icon":1,"baidu-icon":1,"bing-icon":1,"business-insider-icon":1,"dropbox-icon":1,"facebook-icon":1,"flickr-icon":1,"flipboard-icon":1,"forbes-icon":1,"gmail-icon":1,"google-icon":1,"google-drive-icon":1,"googleplus-icon":1,"icq-icon":1,"instagram-icon":1,"lifehacker-icon":1,"linkedin-icon":1,"linkedin-premium-icon":1,"onedrive-icon":1,"outlook-icon":1,"qq-icon":1,"reddit-icon":1,"sesamecredit-icon":1,"skype-icon":1,"slack-icon":1,"slideshare-icon":1,"tumblr-icon":1,"twitter-icon":1,"wechat-icon":1,"weibo-icon":1,"yahoo-icon":1,"yahoo-jp-icon":1,"youtube-icon":1},i={"linkedin-bug":1,"linkedin-logo":1,"premium-badge":1,"premium-wordmark":1,"premium-wordmark-inverse":1,"premium-inverse-badge":1,"hiring-pro":1,"hiring-pro-chinese":1},o={}}))
define("artdeco-icons-web/src/convert-to-mercado",["exports"],(function(e){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=function(e,i){if(!e)return e
if("ui"===i||"nav"===i){const o=t[e]
if(o)return o
if(e.indexOf("linkedin-inbug")>-1||e.indexOf("linkedin-premium-gold")>-1){if(e.indexOf("large")>-1)return"linkedin-bug-medium"
if(e.indexOf("small")>-1)return"linkedin-bug-small"}return"nav"===i?e.replace("small","medium"):n.indexOf(e)>-1?e:e.replace("large","medium")}if("social"===i){return["linkedin-color","linkedin-solid","linkedin-premium-color","linkedin-premium-solid"].indexOf(e)>-1?"linkedin-bug-medium":e}if("scaling"===i)return e.indexOf("premium")>-1?e.replace("-inverse","-on-dark"):e.replace("-inverse","").replace("-full-color","")
if("app"===i&&(e.indexOf("linkedin-bug")>-1||e.indexOf("premium-bug")>-1)){const t=e.substr(e.lastIndexOf("-"),e.length-1)
if("-xlarge"!==t)return`linkedin-bug${t}`}return e}
e.largeIconsInMercado=void 0
const t={"animal-large":"bear-medium","app-switcher-inactive-small":"grid-medium","archive-message-large":"archive-medium","arrows-in-small":"minimize-small","arrows-in-large":"minimize-medium","arrows-out-small":"maximize-small","arrows-out-large":"maximize-medium","at-pebble-large":"mention-medium","bell-large":"bell-outline-medium","bell-filled-large":"bell-fill-medium","bell-slash-large":"bell-off-medium","bold-large":"text-bold-medium","briefcase-large":"job-medium","briefcase-filled-large":"job-medium","brightness-large":"brightness-outline-medium","brightness-filled-large":"brightness-fill-medium","bulleted-list-large":"text-bulleted-list-medium","cancel-large":"close-medium","cancel-small":"close-small","card-plus-large":"content-add-medium","card-remove-large":"clear-medium","caret-down-filled-large":"caret-medium","caret-down-filled-small":"caret-small","checked-list-large":"checklist-medium","circle-verified-large":"verified-medium","closed-caption-large":"closed-captions-outline-medium","closed-caption-filled-large":"closed-captions-fill-medium","compass-large":"discover-medium","content-center-align-large":"content-align-center-medium","content-left-align-large":"content-align-left-medium","content-right-align-large":"content-align-right-medium","contrast-large":"contrast-outline-medium","contrast-filled-large":"contrast-fill-medium","dislike-large":"thumbs-down-outline-medium","dislike-small":"thumbs-down-outline-small","dislike-filled-large":"thumbs-down-fill-medium","dislike-filled-small":"thumbs-down-fill-small","ellipsis-horizontal-large":"overflow-web-ios-medium","ellipsis-horizontal-small":"overflow-web-ios-small","ellipsis-vertical-large":"overflow-android-medium","ellipsis-vertical-small":"overflow-android-small","emoji-face-large":"emoji-medium","enter-large":"join-medium","error-pebble-large":"signal-error-medium","error-pebble-small":"signal-error-small","exit-fullscreen-large":"fullscreen-exit-medium","eyeball-small":"visibility-small","eyeball-large":"visibility-medium","eyeball-slash-small":"visibility-off-small","eyeball-slash-large":"visibility-off-medium","fast-forward-ten-large":"forward-ten-medium","flag-small":"report-small","flag-large":"report-medium","flash-on-large":"flash-medium","food-sandwich-large":"food-medium","forward-large":"share-linkedin-medium","forward-small":"share-linkedin-small","fullscreen-large":"fullscreen-enter-medium","gear-small":"settings-small","gear-large":"settings-medium","gear-filled-large":"settings-medium","globe-small":"globe-americas-small","globe-large":"globe-americas-medium","grid-filled-large":"grid-medium","hamburger-large":"menu-medium","hd-large":"hd-outline-medium","hd-filled-large":"hd-fill-medium","home-filled-large":"home-medium","home-inactive-small":"home-medium","italic-large":"text-italic-medium","jobs-active-small":"job-active-medium","jobs-inactive-small":"job-medium","language-large":"globe-language-medium","large-play-small":"play-large","lightning-bolt-small":"amp-small","like-large":"thumbs-up-outline-medium","like-small":"thumbs-up-outline-small","like-filled-large":"thumbs-up-fill-medium","like-filled-small":"thumbs-up-fill-small","lock-large":"locked-medium","lock-small":"locked-small","linkedin-inbug-color-small":"linkedin-bug-color-small","linkedin-inbug-color-large":"linkedin-bug-color-medium","linkedin-influencer-large":"linkedin-bug-influencer-medium","linkedin-influencer-small":"linkedin-bug-influencer-small","linkedin-influencer-color-large":"linkedin-bug-influencer-color-medium","linkedin-influencer-color-small":"linkedin-bug-influencer-color-small","map-marker-small":"location-marker-small","map-marker-large":"location-marker-medium","messages-large":"send-privately-medium","messages-small":"send-privately-small","messages-filled-large":"send-privately-medium","messages-filled-small":"send-privately-small","messaging-active-small":"messages-active-medium","messaging-inactive-small":"messages-medium","microphone-large":"microphone-outline-medium","microphone-filled-large":"microphone-fill-medium","minus-small":"subtract-small","mobile-large":"phone-medium","mute-large":"volume-mute-medium","notebook-filled-large":"notebook-medium","notifications-active-small":"bell-active-medium","notifications-inactive-small":"bell-fill-medium","notify-pebble-large":"signal-notice-medium","notify-pebble-small":"signal-notice-small","numbered-list-large":"text-numbered-list-medium","paperclip-large":"attachment-medium","paperclip-small":"attachment-small","pencil-large":"edit-medium","pencil-small":"edit-small","pencil-ruler-large":"skills-medium","pencil-ruler-small":"skills-medium","people-filled-large":"people-medium","people-inactive-small":"people-medium","person-remove-large":"remove-connection-medium","person-remove-small":"remove-connection-small","person-tag-large":"tag-person-medium","person-tag-filled-large":"tag-person-medium","person-walking-large":"walk-medium","photo-filter-large":"photo-filter-outline-medium","photo-filter-filled-large":"photo-filter-fill-medium","plus-large":"add-medium","plus-small":"add-small","premium-app-large":"premium-chip-medium","premium-inverse-app-large":"premium-chip-medium","projects-large":"folder-medium","projects-active-small":"folder-active-medium","projects-inactive-small":"folder-medium","qr-reader-large":"scan-qr-code-medium","question-pebble-large":"question-medium","question-pebble-small":"question-small","ribbon-small":"bookmark-outline-small","ribbon-large":"bookmark-outline-medium","ribbon-filled-large":"bookmark-fill-medium","saturation-large":"saturation-outline-medium","saturation-filled-large":"saturation-fill-medium","scan-people-large":"scan-person-medium","scan-plus-large":"scan-add-medium","send-android-small":"send-small","send-android-large":"send-medium","shopping-cart-filled-large":"shopping-cart-active-medium","slideshow-large":"slides-medium","speech-bubble-large":"comment-medium","speech-bubble-small":"comment-small","speech-bubble-slash-large":"comment-off-medium","speech-bubble-slash-small":"comment-off-small","sport-ball-large":"ball-medium","star-small":"star-outline-small","star-large":"star-outline-medium","star-burst-large":"starburst-medium","star-filled-small":"star-fill-small","star-filled-large":"star-fill-medium","stickers-large":"sticker-medium","success-pebble-large":"signal-success-medium","success-pebble-small":"signal-success-small","text-center-align-large":"text-align-center-medium","text-left-align-large":"text-align-left-medium","text-right-align-large":"text-align-right-medium","topic-large":"text-bulleted-list-medium","topics-active-large":"text-bulleted-list-active-medium","to-end-large":"skip-forward-medium","to-start-large":"skip-back-medium","unarchive-message-small":"unarchive-small","unarchive-message-large":"unarchive-medium","unlock-large":"unlocked-medium","unlock-small":"unlocked-small","vignette-large":"vignette-outline-medium","vignette-filled-large":"vignette-fill-medium","volume-max-large":"volume-high-medium","volume-med-large":"volume-mid-medium","volume-min-large":"volume-low-medium","yield-pebble-large":"signal-caution-medium","yield-pebble-small":"signal-caution-small"},n=e.largeIconsInMercado=["shield-large","visibility-large","visibility-off-large","star-fill-large","star-outline-large","star-half-large","play-large"]}))
define("artdeco-icons-web/src/icon-conversion-utils",["exports","artdeco-icons-web/src/convert-to-mercado"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.handleAppIcons=function(e){let t=e.replace(/^app-/,"")
const o=t.indexOf(`-color${n}`)>-1?`-color${n}`:n
t=t.replace(o,"")
if(i[t])return`${t}-medium`
return t}
e.handleNavIcons=function(e,t,i){let o=t
const r=e.indexOf("nav-small-")>-1?"nav-small-":"nav-"
r.indexOf("nav-small")>-1&&(o="small")
if("nav-small-sales-nagivator-inverse-icon"===e)return"sales-navigator-inverse-small"
let a=e.replace(r,"")
if(a.match(/inverse/))return l(o,a.replace(n,""))
a=l(o,i?a.replace(n,"-active"):a.replace(n,"-inactive"))
return a}
e.handleScalingIcons=function(e,t){if("premium-inverse-badge"===e)return`premium-badge-inverse-${o[t]}`
return`${e}-${o[t]}`}
e.handleSocialIcons=function(e,t){let i
i=t?e.replace(n,"-color"):e.replace(n,"-solid")
return i}
e.handleUIIcons=function(e,t){let i=e
if(e.indexOf("filled")>-1){-1===e.indexOf("filled-icon")&&(i=`${e.replace("-filled","")}-filled`)
i=i.replace(n,"")}else e.indexOf(n)>-1&&(i=e.replace(n,""))
if(r[i])return l("small",i)
return l(t,i)}
const n="-icon",i={"influencer-bug":1,"influencer-bug-black":1,"linkedin-bug":1,"linkedin-bug-black":1,jobs:1,pointdrive:1,"talent-insights":1,"premium-bug":1,"premium-bug-gold":1,"premium-bug-inverse":1},o={"8dp":"xxxsmall","16dp":"small","24dp":"large","32dp":"xlarge","14dp":"xxsmall","21dp":"xsmall","28dp":"small","34dp":"medium","40dp":"large","48dp":"xlarge",small:"small",large:"large",medium:"medium",xsmall:"xsmall",xxsmall:"xxsmall",xlarge:"xlarge"},r={"check-xsmall":1,"lightning-bolt":1,openlink:1,"verified-badge":1},a=t.largeIconsInMercado.map((e=>e.replace("-large","")))
function l(){let e=arguments.length>0&&void 0!==arguments[0]?arguments[0]:"large",t=arguments.length>1?arguments[1]:void 0
const n={small:1,large:1}
a.includes(t)&&(n.medium=1)
return n[e]?`${t}-${e}`:`${t}-large`}}))
define("artdeco-icons-web/src/icons",["exports","rsvp","artdeco-icons-web/src/convert-icon-name","artdeco-icons-web/src/convert-to-mercado"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
const o="undefined"!=typeof FastBoot,r="artdeco-icons/static/images/icons.svg"
let a={document:o?null:document,customSpriteID:null,sourceEl:null,loadingPromise:null,iconCache:{},nextTitleId:1,loadListeners:[]}
const l=function(){},s=e=>{const t=a.document.getElementById(e)
return t?t.getAttribute("content"):""}
function c(e){let t=e
t=e.cloneNode(!0)
t.removeAttribute("id")
return t}function u(e){let{dataType:t,error:n,success:i,url:o,isAsync:r,isCustomSprite:a}=e
const l=new XMLHttpRequest
a||(o=s("artdeco-icons/static/images/sprite-asset")||s(o))
l.open("GET",o,r)
const c=this&&this!==window?this:l
if(r&&"xml"===t){c.responseType="document"
c.overrideMimeType&&c.overrideMimeType("text/xml")}c.onload=function(){if(200===c.status){const e="xml"===t?function(e){const t=e.responseXML
return t&&t.firstChild?t.firstChild:(new DOMParser).parseFromString(e.responseText,"application/xml").firstChild}(c):c.responseText
i&&i(e)}else n&&n(`Request for ${o} failed with code ${c.status}.`)}
c.onerror=n
c.send()}const d={init:function(e){a.document=e&&e.document},reset:function(){a={document:a.document||null,sourceEl:null,loadingPromise:null,iconCache:{},nextTitleId:1,loadListeners:[]}},load:function(){let e=!(arguments.length>0&&void 0!==arguments[0])||arguments[0],n=arguments.length>1?arguments[1]:void 0,i=arguments.length>2?arguments[2]:void 0
if(a.loadingPromise)return a.loadingPromise
i&&(a.customSpriteID=i)
a.loadingPromise=new t.default.Promise((function(t,i){if(o){const e=FastBoot.require("fs"),i=FastBoot.require("path"),o=FastBoot.require("xmldom")
let l
l=n?e.readFileSync(i.join(FastBoot.distPath,n)).toString():e.readFileSync(i.join(FastBoot.distPath,"assets",r)).toString()
l=(new o.DOMParser).parseFromString(l).firstChild
a.document=(new o.DOMImplementation).createDocument()
a.sourceEl=l
t(l)}else u({isAsync:e,url:n||r,isCustomSprite:!!n,dataType:"xml",error:i,success:e=>{a.sourceEl=e
!function(){if(a.document&&a.document.getElementsByTagName("base")[0]&&a.sourceEl){const e=window.location.href.replace(window.location.hash,""),t={mask:a.sourceEl.querySelectorAll("[*|mask^=url]"),fill:a.sourceEl.querySelectorAll("[*|fill^=url]"),style:a.sourceEl.querySelectorAll('[*|style^="fill:url"],[*|style^="fill: url"]')},n=a.sourceEl.querySelectorAll("style")
Object.keys(t).forEach((n=>{[].slice.call(t[n]).filter((e=>e.getAttribute(n).indexOf("url(#")>=0)).forEach((t=>{t.setAttribute(n,t.getAttribute(n).replace("url(#",`url(${e}#`))}))}));[].forEach.call(n,(t=>{const n=/url\(#([^)]+)\)/g
t.textContent&&n.test(t.textContent)&&(t.textContent=`/*<![CDATA[*/${t.textContent.replace(n,(function(t){const n=t.split("#")
return`${n[0]}${e}#${n[1]}`}))}/*]]>*/`)}))}}()
const{loadListeners:n}=a
if(n&&n.length){for(let e=0;e<n.length;e++)n[e](a.sourceEl)
a.loadListeners.length=0}!function(e,t,n){const i=a.document.createEvent("CustomEvent")
i.initCustomEvent(t,!0,!0,n)
e.dispatchEvent(i)}(a.document,"artdeco-icons-loaded")
t(e)}})}))
return a.loadingPromise},isLoaded:function(){return!!a.sourceEl},getIcon(e){let t=arguments.length>1&&void 0!==arguments[1]?arguments[1]:{},i=arguments.length>2&&void 0!==arguments[2]?arguments[2]:l
const{size:o,color:r,active:s}=t,{newType:c,category:u}=(0,n.default)(e,o,r,s),m=function(e){e?i(null,function(e,t){let n=e.getAttribute("data-supported-dps")
if(!n)return e.cloneNode(!0)
n=n.split(" ")
const i=n.length
if(0===i)return e
if(1===i||"small"===t){const[t,i]=n[0].split("x")
e.setAttribute("width",t)
e.setAttribute("height",i)}else{const[t,i]=n[1].split("x")
e.setAttribute("width",t)
e.setAttribute("height",i)}return e.cloneNode(!0)}(e,o)):i(`Unable to find icon "${c}"`,null)}
let p=this.getIconFromCache(c,u)||this.getIconFromCache(e,u)||this.getIconFromCache(this.computeMercadoName(e,t),a.customSpriteID)
null==p?d.getSourceEl((n=>{p=this.findIconInSVG(n,c,e,u,t)
m(p)})):m(p)},findIconInSVG(e,t,n,o,r){let l,s
const{customSpriteID:u}=a
e&&e.getAttribute&&(l=e.getAttribute("id"))
if(l&&(l===u||"mercado-icons"===l)){const a=(0,i.default)(t,o),l=["system-icons","logo-lockup-text","logos-bugs","app-icons","social-icons"].reduce(((t,n)=>{const i=this.findElementInSVGDoc(e,n,"defs"),o=i?i.getElementsByTagName("svg"):[]
return t.concat([].slice.call(o))}),[])
s=this.findElementInNodeListById(l,a)
if(s)s.setAttribute("class","mercado-match")
else{const e=this.computeMercadoName(n,r)
s=this.findElementInNodeListById(l,e)}s=s&&c(s)
this.setCache(n,u,s)}if(!s){const n="ui"===o||"system-icons"===o?t.replace("-medium","-large"):t,i=this.findElementInSVGDoc(e,o,"defs")
i&&i.querySelector?s=i.querySelector('[id="'.concat(n,'"]')):i&&(s=this.findElementInNodeListById([].slice.call(i.getElementsByTagName("svg")),n))
s=s&&c(s)
this.setCache(t,o,s)}return s},findElementInSVGDoc(e,t){let n=arguments.length>2&&void 0!==arguments[2]?arguments[2]:"svg"
return e.getElementById?e.getElementById(t):e.querySelector?e.querySelector(`[id="${t}"]`):this.findElementInNodeListById([].slice.call(e.getElementsByTagName(n)),t)},findElementInNodeListById:(e,t)=>e.find((e=>{if(e){const n=e.getAttributeNode("id")
if(n&&n.value===t)return e}return null})),computeMercadoName(e,t){let n
const{color:i,size:o}=t
o?n=`${e}-${o}`:!1===i?n=`${e}-solid`:!0===i&&(n=`${e}-color`)
return n},getIconFromCache:(e,t)=>e&&t?a.iconCache[`${e}-${t}`]:null,setCache(e,t,n){e&&t&&(a.iconCache[`${e}-${t}`]=n)},getSourceEl(){let e=arguments.length>0&&void 0!==arguments[0]?arguments[0]:l
d.isLoaded()?e(a.sourceEl):a.loadListeners.push(e)},setIconTitle(e,t){const n=a.document.createElementNS("http://www.w3.org/2000/svg","title"),i="li-icon-title-"+a.nextTitleId++
n.textContent=t
n.setAttribute("id",i)
e.insertBefore(n,e.firstChild)
e.setAttribute("aria-labelledby",i)},getState:()=>a}
e.default=d}))
define("artdeco-icons-web/src/li-icon",["exports","artdeco-icons-web/src/icons"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.buildLoaderSpinner=a
e.default=void 0
e.toggleBooleanAttrs=r
const n="undefined"!=typeof FastBoot,i=["active","animate"]
let o
if(n){const e=FastBoot.require("xmldom")
o=(new e.DOMImplementation).createDocument()}else o=document
function r(e,t){for(let n=0,o=i.length;n<o;n++){const o=i[n]
t[o]?e.setAttribute(o,"true"):e.removeAttribute(o)}}function a(e){const t=e.getAttribute("type")||""
if(t&&"loader"===t){const t=o.createElement("div")
t.className="artdeco-spinner"
for(let e=0;e<12;e++){const e=o.createElement("span")
e.className="artdeco-spinner-bars"
t.appendChild(e)}e.appendChild(t)}}const l={init:function(e){o=e&&e.document},create:function(e){const t=o.createElement("li-icon")
l.setAttrs(t,e)
return t},createA11yCaption(e){const t=o.createElement("span")
t.setAttribute("class","a11y-text")
t.textContent=e
return t},createWithIcon(e){const t=l.create(e)
l.setIcon(t,e.type,e.size,e.color,e.active)
return t},setIcon(e,n,i,o,r){for(;e.firstChild;)e.removeChild(e.firstChild)
n&&"loader"===n?a(e):t.default.getIcon(n,{size:i,color:o,active:r},((t,i)=>{if(i&&"loader"!==n){i.setAttribute("focusable",!1)
e.appendChild(i)}}))},setAttrs(e,t){const{size:n,type:i,color:o}=t,a=t.class||""
e.setAttribute("aria-hidden","true")
e.setAttribute("type",i)
r(e,t)
a&&e.setAttribute("class",a)
n?e.setAttribute("size",n):e.removeAttribute("size")
o?e.setAttribute("color",o):e.removeAttribute("color")},setA11yText(e,t){if(t){e.removeAttribute("aria-hidden")
e.setAttribute("role","img")
e.setAttribute("aria-label",t)}else if(!e.getAttribute("aria-hidden")){e.removeAttribute("aria-label")
e.removeAttribute("role")
e.setAttribute("aria-hidden","true")}}}
e.default=l}))
define("artdeco-icons-web/templates/components/linkedin-logo",["exports","@ember/template-factory"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=(0,t.createTemplateFactory)({id:"x4CpL/Ic",block:'[[[1,[28,[35,0],null,[["type","size","color","class"],[[30,0,["iconType"]],[30,0,["size"]],[30,0,["iconVariant"]],[30,0,["colorClassname"]]]]]],[1,"\\n"],[10,1],[15,0,[29,["logo-text ",[30,0,["colorClassname"]]]]],[12],[18,1,null],[13],[1,"\\n"]],["&default"],false,["li-icon","yield"]]',moduleName:"artdeco-icons-web/templates/components/linkedin-logo.hbs",isStrictMode:!1})}))
define("artdeco-pill/components/artdeco-pill-base",["exports","@ember/component","@ember/object","artdeco-pill/utils/constants","artdeco-pill/utils/artdeco-pill-base"],(function(e,t,n,i,o){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=t.default.extend({classNames:o.classNames,classNameBindings:o.classNameBindings,color:i.PILL_COLOR_DEFAULT,inverse:!1,size:i.PILL_SIZE_DEFAULT,tagName:"span",ariaDisabled:(0,n.computed)("disabled",(function(){return(0,n.get)(this,"disabled")?"true":null})),init(){this._super(...arguments);(0,o.setClassNameProps)(this)}})}))
define("artdeco-pill/components/artdeco-pill-choice-group",["exports","@ember/debug","@ember/component","@ember/object","@ember/utils","artdeco-pill/templates/components/artdeco-pill-choice-group"],(function(e,t,n,i,o,r){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=n.default.extend({attributeBindings:["a11yText:aria-label","_role:role"],classNameBindings:["inverse:artdeco-pill-choice-group--inverse"],classNames:["artdeco-pill-choice-group"],layout:r.default,_role:"radiogroup",selection:"",inverse:!1,a11yText(){return this.args.a11yText||""},_assertParams(){},init(){this._super(...arguments)
this._assertParams()
this.default&&(0,i.set)(this,"selection",this.default)},actions:{onChoice(e){var t;(0,i.set)(this,"selection",e)
null===(t=this.onSelect)||void 0===t||t.call(this,e)},onKeyDown(e){if((0,o.isPresent)((0,i.get)(this,"groupUniqueId"))){const t=(0,i.get)(this,"groupUniqueId"),n=Array.from(document.querySelector(`#${t}`).querySelectorAll("button"))
let o=n.findIndex((e=>e===document.activeElement)),r=!1
if("ArrowDown"===e.key||"ArrowRight"===e.key){r=!0
o++
for(;o<n.length&&n[o].disabled;)o++}else if("ArrowLeft"===e.key||"ArrowUp"===e.key){r=!0
o--
for(;o>0&&n[o].disabled;)o--}r&&n[o]&&!n[o].disabled&&n[o].focus()}}}})}))
define("artdeco-pill/components/artdeco-pill-choice",["exports","@ember/debug","@ember/object","@ember/object/computed","@ember/utils","artdeco-pill/utils/constants","artdeco-pill/components/artdeco-pill-base","artdeco-pill/templates/components/artdeco-pill-choice"],(function(e,t,n,i,o,r,a,l){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=a.default.extend({attributeBindings:["a11yText:aria-label","_controlType:type","tabindex","_role:role","disabled:disabled","ariaChecked:aria-checked","ariaDisabled:aria-disabled"],a11yText(){return this.args.a11yText||this.args.text},_controlType:"button",_role:"radio",layout:l.default,tagName:"button",type:r.PILL_TYPES.CHOICE,isDisabled:(0,i.bool)("disabled"),selected:(0,n.computed)("selection","value",(function(){return(0,n.get)(this,"selection")===(0,n.get)(this,"value")})),ariaChecked:(0,n.computed)("selected",(function(){return(0,n.get)(this,"selected")?"true":"false"})),_selectedAriaState:(0,i.bool)("selected"),_assertParams(){},init(){this._super(...arguments)
this._assertParams()},click(){var e
null===(e=this.onChoice)||void 0===e||e.call(this,this.value)}})}))
define("artdeco-pill/components/artdeco-pill-dismiss",["exports","@ember/debug","@ember/object","@ember/utils","artdeco-pill/utils/constants","artdeco-pill/templates/components/artdeco-pill-dismiss","artdeco-pill/components/artdeco-pill-base","@ember/service"],(function(e,t,n,i,o,r,a,l){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=a.default.extend({i18n:(0,l.inject)("i18n"),layout:r.default,tagName:"button",attributeBindings:["ariaLabel:aria-label","disabled","buttonType:type"],ariaLabel:(0,n.computed)("a11yText",(function(){return(0,n.get)(this,"a11yText")||(0,n.get)(this,"i18n").lookupTranslation("artdeco-pill@components/artdeco-pill-dismiss","i18n__dismiss_pill__dismiss_button")()})),buttonType:"button",type:o.PILL_TYPES.DISMISS,_assertParams(){},init(){this._super(...arguments)
this._assertParams()},click(){var e
null===(e=this.onDismiss)||void 0===e||e.call(this)}})}))
define("artdeco-pill/components/artdeco-pill-input",["exports","@ember/debug","@ember/object","@ember/utils","artdeco-pill/templates/components/artdeco-pill-input","artdeco-pill/utils/constants","artdeco-pill/components/artdeco-pill-base","ember-lifeline"],(function(e,t,n,i,o,r,a,l){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=a.default.extend({layout:o.default,active:(0,n.computed)("confirmed","hasFocus","value",(function(){const{confirmed:e,hasFocus:t,value:o}=(0,n.getProperties)(this,["confirmed","hasFocus","value"])
return t||!e&&(0,i.isPresent)(o)})).readOnly(),confirmed:(0,n.computed)("lastValue","value",(function(){const{lastValue:e,value:t}=(0,n.getProperties)(this,["lastValue","value"])
return(0,i.isPresent)(t)&&e===t})).readOnly(),disabled:!1,ghostValue:(0,n.computed)("value","label",(function(){const{value:e,label:t}=(0,n.getProperties)(this,["value","label"])
return(0,i.isPresent)(e)?e:t})).readOnly(),hasFocus:!1,inputClass:"artdeco-pill__input",inputType:"text",tagName:"span",type:r.PILL_TYPES.INPUT,value:"",_assertParams(){},_clear(){var e;(0,n.setProperties)(this,{lastValue:"",value:""});(0,l.runTask)(this,(()=>{this.inputElement.focus()}),0)
null===(e=this.onClear)||void 0===e||e.call(this)},_confirm(){var e
const t=(0,n.get)(this,"value")
if((0,i.isEmpty)(t))this._clear()
else{(0,n.set)(this,"lastValue",t)
null===(e=this.onConfirm)||void 0===e||e.call(this,t)}},_setInputId(){(0,n.set)(this,"inputId",`artdeco-pill__input-${this.elementId}`)},_setValue(){(0,n.set)(this,"value",this.inputElement.value)},init(){this._super(...arguments)
const e=(0,n.get)(this,"value");(0,i.isPresent)(e)&&(0,n.set)(this,"lastValue",e)
this._assertParams()
this._setInputId()},didInsertElement(){this._super(...arguments)
const e=this.element.querySelector(`#${(0,n.get)(this,"inputId")}`);(0,n.set)(this,"inputElement",e)},actions:{handleClear(){this._clear()},handleConfirm(){this._confirm()},handleBlur(){var e;(0,n.set)(this,"hasFocus",!1)
null===(e=this.onBlur)||void 0===e||e.call(this)},handleFocus(){var e;(0,n.set)(this,"hasFocus",!0)
null===(e=this.onFocus)||void 0===e||e.call(this)},handleInput(e){var t
this._setValue()
null===(t=this.onInput)||void 0===t||t.call(this,e)}}})}))
define("artdeco-pill/components/artdeco-pill-link",["exports","@ember/legacy-built-in-components","@ember/object","@ember/object/computed","artdeco-pill/utils/constants","artdeco-pill/utils/artdeco-pill-base"],(function(e,t,n,i,o,r){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=t.LinkComponent.extend({attributeBindings:["ariaDisabled:aria-disabled"],activeClass:o.PILL_LINK_ACTIVE_CLASS,ariaRole:"button",classNames:r.classNames,classNameBindings:r.classNameBindings,color:o.PILL_COLOR_DEFAULT,size:o.PILL_SIZE_DEFAULT,type:o.PILL_TYPES.LINK,inverse:!1,isDisabled:(0,i.bool)("disabled"),tabindex:(0,n.computed)("isDisabled",(function(){return(0,n.get)(this,"isDisabled")?"-1":null})),ariaDisabled:(0,n.computed)("disabled",(function(){return(0,n.get)(this,"disabled")?"true":null})),init(){this._super(...arguments);(0,r.setClassNameProps)(this)}})}))
define("artdeco-pill/components/artdeco-pill-toggle",["exports","@ember/debug","@ember/object","@ember/utils","artdeco-pill/utils/constants","artdeco-pill/components/artdeco-pill-base","artdeco-pill/templates/components/artdeco-pill-toggle"],(function(e,t,n,i,o,r,a){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=r.default.extend({attributeBindings:["a11yText:aria-label","_controlType:type","_selectedAriaState:aria-checked","disabled","tabindex","_role:role"],a11yText(){return this.args.a11yText||this.args.text},_controlType:"button",_role:"checkbox",layout:a.default,tagName:"button",type:o.PILL_TYPES.TOGGLE,selected:!1,_selectedAriaState:(0,n.computed)("selected",(function(){return(0,n.get)(this,"selected")?"true":"false"})),_assertParams(){},init(){this._super(...arguments)
this._assertParams()},click(){if(!(0,n.get)(this,"disabled")){var e
null===(e=this.onToggle)||void 0===e||e.call(this)}}})}))
define("artdeco-pill/templates/components/artdeco-pill-choice-group",["exports","@ember/template-factory"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=(0,t.createTemplateFactory)({id:"gThwY6VV",block:'[[[18,1,[[28,[37,1],null,[["choice-pill"],[[50,"artdeco-pill-choice",0,null,[["selection","inverse","onChoice"],[[30,0,["selection"]],[30,0,["inverse"]],[28,[37,3],[[30,0],"onChoice"],null]]]]]]],[28,[37,1],null,[["onKeyDownEvent"],[[28,[37,3],[[30,0],"onKeyDown"],null]]]]]],[1,"\\n"]],["&default"],false,["yield","hash","component","action"]]',moduleName:"artdeco-pill/templates/components/artdeco-pill-choice-group.hbs",isStrictMode:!1})}))
define("artdeco-pill/templates/components/artdeco-pill-choice",["exports","@ember/template-factory"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=(0,t.createTemplateFactory)({id:"R9Sg6tzV",block:'[[[41,[48,[30,1]],[[[1,"  "],[18,1,null],[1,"\\n"]],[]],[[[1,"  "],[1,[30,0,["text"]]],[1,"\\n"]],[]]]],["&default"],false,["if","has-block","yield"]]',moduleName:"artdeco-pill/templates/components/artdeco-pill-choice.hbs",isStrictMode:!1})}))
define("artdeco-pill/templates/components/artdeco-pill-dismiss",["exports","@ember/template-factory"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=(0,t.createTemplateFactory)({id:"cCVFaH39",block:'[[[10,1],[14,0,"artdeco-pill__text"],[12],[1,"\\n"],[41,[48,[30,1]],[[[1,"    "],[18,1,null],[1,"\\n"]],[]],[[[1,"    "],[1,[30,0,["text"]]],[1,"\\n"]],[]]],[13],[1,"\\n\\n"],[1,[28,[35,3],null,[["type","size","class"],["cancel-icon","small","artdeco-pill__icon"]]]],[1,"\\n"]],["&default"],false,["if","has-block","yield","li-icon"]]',moduleName:"artdeco-pill/templates/components/artdeco-pill-dismiss.hbs",isStrictMode:!1})}))
define("artdeco-pill/templates/components/artdeco-pill-input",["exports","@ember/template-factory"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=(0,t.createTemplateFactory)({id:"lKSaSJdi",block:'[[[10,"label"],[14,0,"artdeco-pill__label artdeco-pill__label--hidden"],[15,"for",[29,[[30,0,["inputId"]]]]],[12],[1,"\\n  "],[1,[30,0,["label"]]],[1,"\\n"],[13],[1,"\\n\\n"],[10,0],[14,0,"artdeco-pill__input-container"],[12],[1,"\\n"],[1,"  "],[10,0],[14,"aria-hidden","true"],[15,0,[29,["artdeco-pill__ghost ",[52,[30,0,["value"]],"artdeco-pill__ghost--value-present"]]]],[12],[1,[30,0,["ghostValue"]]],[13],[1,"\\n"],[41,[48,[30,1]],[[[1,"    "],[18,1,[[28,[37,3],null,[["inputClass","inputId","disabled","readonly","value","handleBlur","handleFocus","handleInput"],[[30,0,["inputClass"]],[30,0,["inputId"]],[30,0,["disabled"]],[30,0,["readonly"]],[30,0,["value"]],[28,[37,4],[[30,0],"handleBlur"],null],[28,[37,4],[[30,0],"handleFocus"],null],[28,[37,4],[[30,0],"handleInput"],null]]]]]],[1,"\\n"]],[]],[[[1,"    "],[8,[39,5],[[16,0,[30,0,["inputClass"]]],[16,1,[30,0,["inputId"]]],[16,"disabled",[30,0,["disabled"]]],[16,"readonly",[30,0,["readonly"]]],[24,"dir","auto"],[4,[38,6],["focusin",[28,[37,4],[[30,0],"handleFocus"],null]],null],[4,[38,6],["focusout",[28,[37,4],[[30,0],"handleBlur"],null]],null],[4,[38,6],["keyup",[28,[37,4],[[30,0],"handleInput"],null]],null]],[["@type","@value","@enter","@escape-press"],[[30,0,["inputType"]],[30,0,["value"]],[28,[37,4],[[30,0],"handleConfirm"],null],[28,[37,4],[[30,0],"handleClear"],null]]],null],[1,"\\n"]],[]]],[13],[1,"\\n\\n"],[41,[48,[30,1]],[[[41,[51,[30,0,["value"]]],[[[1,"    "],[11,"button"],[16,"aria-label",[29,[[52,[30,0,["a11yText"]],[30,0,["a11yText"]],[52,[30,0,["confirmed"]],[28,[37,8],["i18n__input_pill__dismiss_button","artdeco-pill/templates/components/artdeco-pill-input"],null],[28,[37,8],["i18n__input_pill__confirm_change_button","artdeco-pill/templates/components/artdeco-pill-input"],null]]]]]],[24,0,"artdeco-pill__button"],[16,"disabled",[30,0,["disabled"]]],[24,4,"button"],[4,[38,4],[[30,0],[52,[30,0,["confirmed"]],"handleClear","handleConfirm"]],null],[12],[1,"\\n      "],[1,[28,[35,9],null,[["class","type","size"],["artdeco-pill__icon",[52,[30,0,["confirmed"]],"cancel-icon","plus-icon"],"small"]]]],[1,"\\n    "],[13],[1,"\\n"]],[]],null]],[]],[[[1,"  "],[11,"button"],[16,"aria-label",[29,[[52,[30,0,["a11yText"]],[30,0,["a11yText"]],[52,[30,0,["confirmed"]],[28,[37,8],["i18n__input_pill__dismiss_button","artdeco-pill/templates/components/artdeco-pill-input"],null],[28,[37,8],["i18n__input_pill__confirm_change_button","artdeco-pill/templates/components/artdeco-pill-input"],null]]]]]],[24,0,"artdeco-pill__button"],[16,"disabled",[30,0,["disabled"]]],[24,4,"button"],[4,[38,4],[[30,0],[52,[30,0,["confirmed"]],"handleClear","handleConfirm"]],null],[12],[1,"\\n    "],[1,[28,[35,9],null,[["class","type","size"],["artdeco-pill__icon",[52,[30,0,["confirmed"]],"cancel-icon","plus-icon"],"small"]]]],[1,"\\n  "],[13],[1,"\\n"]],[]]]],["&default"],false,["if","has-block","yield","hash","action","input","on","unless","t","li-icon"]]',moduleName:"artdeco-pill/templates/components/artdeco-pill-input.hbs",isStrictMode:!1})}))
define("artdeco-pill/templates/components/artdeco-pill-toggle",["exports","@ember/template-factory"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=(0,t.createTemplateFactory)({id:"9R3gz03z",block:'[[[10,1],[14,0,"artdeco-pill__text"],[12],[1,"\\n"],[41,[48,[30,1]],[[[1,"    "],[18,1,null],[1,"\\n"]],[]],[[[1,"    "],[1,[30,0,["text"]]],[1,"\\n"]],[]]],[13],[1,"\\n\\n"],[1,[28,[35,3],null,[["class","type","size"],["artdeco-pill__icon",[52,[30,0,["selected"]],"check-icon","plus-icon"],"small"]]]]],["&default"],false,["if","has-block","yield","li-icon"]]',moduleName:"artdeco-pill/templates/components/artdeco-pill-toggle.hbs",isStrictMode:!1})}))
define("artdeco-pill/utils/artdeco-pill-base",["exports","@ember/debug","@ember/object","artdeco-pill/utils/constants","artdeco-pill/utils/object"],(function(e,t,n,i,o){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.classNames=e.classNameBindings=void 0
e.getColorClass=r
e.getSizeClass=a
e.getTypeClass=l
e.setClassNameProps=function(e){(0,n.setProperties)(e,{_colorClass:r(e),_sizeClass:a(e),_typeClass:l(e)})}
e.classNames=["artdeco-pill"],e.classNameBindings=["_colorClass","_sizeClass","_typeClass","active:artdeco-pill--active","confirmed:artdeco-pill--confirmed","inverse:artdeco-pill--inverse","selected:artdeco-pill--selected","disabled:artdeco-pill--disabled"]
function r(e){const t=(0,n.get)(e,"color")
return`artdeco-pill--${t}`}function a(e){const t=(0,n.get)(e,"size")
return`artdeco-pill--${t}`}function l(e){const t=(0,n.get)(e,"type")
return`artdeco-pill--${t}`}}))
define("artdeco-pill/utils/constants",["exports"],(function(e){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.PILL_TYPES=e.PILL_SIZE_DEFAULT=e.PILL_SIZES=e.PILL_LINK_ACTIVE_CLASS=e.PILL_COLOR_DEFAULT=e.PILL_COLORS=e.GHOST_STYLES=void 0
e.GHOST_STYLES=["display: inline-block;","height: 0;","overflow: hidden;","position: absolute;","top: 0;","visibility: hidden;","white-space: pre;"].join(""),e.PILL_COLOR_DEFAULT="slate",e.PILL_COLORS=["blue","green","orange","red","slate","teal"],e.PILL_LINK_ACTIVE_CLASS="artdeco-pill__link--active",e.PILL_SIZE_DEFAULT=2,e.PILL_SIZES=[1,2,3],e.PILL_TYPES={DISMISS:"dismiss",INPUT:"input",LINK:"link",TOGGLE:"toggle",CHOICE:"choice"}}))
define("artdeco-pill/utils/object",["exports"],(function(e){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.hasValue=function(e,t){return Object.keys(e).map((t=>e[t])).indexOf(t)>-1}}))
define("ember-batcher/batcher",["exports","ember-test-waiters"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.mutateDOM=function(e){let t=i.beginAsync()
r.unshift([t,e])
u()}
e.readDOM=function(e){let t=n.beginAsync()
o.unshift([t,e])
u()}
e.visibilityChange=void 0
const n=(0,t.buildWaiter)("ember-batcher: readDOM"),i=(0,t.buildWaiter)("ember-batcher: mutateDOM"),o=[],r=[]
let a=()=>{}
e.visibilityChange=a
let l=!1,s=!1
const c="object"==typeof window&&"function"==typeof window.requestAnimationFrame?e=>{let t=()=>{if(!s){s=!0
e()}}
setTimeout(t,20)
return requestAnimationFrame(t)}:e=>setTimeout(e)
0
function u(){if(!l){l=!0
c((()=>{let e,t
for(e=0,t=o.length;e<t;e++){let[e,t]=o.pop()
t()
n.endAsync(e)}for(e=0,t=r.length;e<t;e++){let[e,t]=r.pop()
t()
i.endAsync(e)}l=!1
s=!1;(r.length>0||o.length>0)&&u()}))}}}))
define("ember-batcher/index",["exports","ember-batcher/batcher"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
Object.defineProperty(e,"mutateDOM",{enumerable:!0,get:function(){return t.mutateDOM}})
Object.defineProperty(e,"readDOM",{enumerable:!0,get:function(){return t.readDOM}})}))
define("ember-lifeline/debounce-task",["exports","@ember/debug","@ember/runloop","@ember/destroyable"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.cancelDebounce=function(e,t){if(!o.has(e))return
const i=o.get(e)
if(!i.has(t))return
const{cancelId:r}=i.get(t)
i.delete(t);(0,n.cancel)(r)}
e.debounceTask=function(e,t){if(e.isDestroying)return
for(var r=arguments.length,a=new Array(r>2?r-2:0),l=2;l<r;l++)a[l-2]=arguments[l]
const s=a[a.length-1]
"boolean"==typeof s&&a[a.length-2]
let c,u=o.get(e)
if(!u){u=new Map
o.set(e,u);(0,i.registerDestructor)(e,(d=u,function(){0!==d.size&&d.forEach((e=>(0,n.cancel)(e.cancelId)))}))}var d
c=u.has(t)?u.get(t).debouncedTask:function(){u.delete(t)
e[t](...arguments)}
let m=(0,n.debounce)(e,c,...a)
u.set(t,{debouncedTask:c,cancelId:m})}
const o=new WeakMap}))
define("ember-lifeline/dom-event-listeners",["exports","@ember/debug","@ember/runloop","@ember/destroyable"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.PASSIVE_SUPPORTED=void 0
e.addEventListener=function(e,t,c,u,d){s(t,c,u)
let m=(0,n.bind)(e,u),p=o.get(e)
if(void 0===p){p=[]
o.set(e,p)}0===p.length&&(0,i.registerDestructor)(e,function(e){return function(){if(void 0!==e){for(let t=0;t<e.length;t+=a){let n=e[t+l.Target],i=e[t+l.eventName],o=e[t+l.callback],r=e[t+l.options]
n.removeEventListener(i,o,r)}e.length=0}}}(p))
r||(d=void 0)
t.addEventListener(c,m,d)
p.push(t,c,m,u,d)}
e.removeEventListener=function(e,t,n,i,c){s(t,n,i)
let u=o.get(e)
if(void 0===u||0===u.length)return
r||(c=void 0)
for(let e=0;e<u.length;e+=a)if(u[e+l.Target]===t&&u[e+l.eventName]===n&&u[e+l.originalCallback]===i){let i=u[e+l.callback]
t.removeEventListener(n,i,c)
u.splice(e,a)
break}}
const o=new WeakMap,r=e.PASSIVE_SUPPORTED=(()=>{let e=!1
try{let t=Object.defineProperty({},"passive",{get:()=>e=!0})
window.addEventListener("test",null,t)}catch(e){}return e})(),a=5
var l
!function(e){e[e.Target=0]="Target"
e[e.eventName=1]="eventName"
e[e.callback=2]="callback"
e[e.originalCallback=3]="originalCallback"
e[e.options=4]="options"}(l||(l={}))
function s(e,t,n){}}))
define("ember-lifeline/index",["exports","ember-lifeline/run-task","ember-lifeline/poll-task","ember-lifeline/debounce-task","ember-lifeline/dom-event-listeners","ember-lifeline/utils/disposable","ember-lifeline/utils/get-timeout-or-test-fallback","ember-lifeline/mixins/run","ember-lifeline/mixins/dom","ember-lifeline/mixins/disposable"],(function(e,t,n,i,o,r,a,l,s,c){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
Object.defineProperty(e,"ContextBoundEventListenersMixin",{enumerable:!0,get:function(){return s.default}})
Object.defineProperty(e,"ContextBoundTasksMixin",{enumerable:!0,get:function(){return l.default}})
Object.defineProperty(e,"DisposableMixin",{enumerable:!0,get:function(){return c.default}})
Object.defineProperty(e,"Token",{enumerable:!0,get:function(){return n.Token}})
Object.defineProperty(e,"_setRegisteredPollers",{enumerable:!0,get:function(){return n._setRegisteredPollers}})
Object.defineProperty(e,"_setRegisteredTimers",{enumerable:!0,get:function(){return t._setRegisteredTimers}})
Object.defineProperty(e,"addEventListener",{enumerable:!0,get:function(){return o.addEventListener}})
Object.defineProperty(e,"cancelDebounce",{enumerable:!0,get:function(){return i.cancelDebounce}})
Object.defineProperty(e,"cancelPoll",{enumerable:!0,get:function(){return n.cancelPoll}})
Object.defineProperty(e,"cancelTask",{enumerable:!0,get:function(){return t.cancelTask}})
Object.defineProperty(e,"debounceTask",{enumerable:!0,get:function(){return i.debounceTask}})
Object.defineProperty(e,"getTimeoutOrTestFallback",{enumerable:!0,get:function(){return a.getTimeoutOrTestFallback}})
Object.defineProperty(e,"pollTask",{enumerable:!0,get:function(){return n.pollTask}})
Object.defineProperty(e,"queuedPollTasks",{enumerable:!0,get:function(){return n.queuedPollTasks}})
Object.defineProperty(e,"registerDisposable",{enumerable:!0,get:function(){return r.registerDisposable}})
Object.defineProperty(e,"removeEventListener",{enumerable:!0,get:function(){return o.removeEventListener}})
Object.defineProperty(e,"runDisposables",{enumerable:!0,get:function(){return r.runDisposables}})
Object.defineProperty(e,"runTask",{enumerable:!0,get:function(){return t.runTask}})
Object.defineProperty(e,"scheduleTask",{enumerable:!0,get:function(){return t.scheduleTask}})
Object.defineProperty(e,"setShouldPoll",{enumerable:!0,get:function(){return n.setShouldPoll}})
Object.defineProperty(e,"throttleTask",{enumerable:!0,get:function(){return t.throttleTask}})}))
define("ember-lifeline/mixins/disposable",["exports","@ember/object/mixin","@ember/debug","ember-lifeline/utils/disposable"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=t.default.create({init(){this._super(...arguments)},registerDisposable(e){(0,i.registerDisposable)(this,e)}})}))
define("ember-lifeline/mixins/dom",["exports","@ember/object/mixin","@ember/debug","ember-lifeline/dom-event-listeners"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=t.default.create({init(){this._super(...arguments)},addEventListener(e,t,n,r){let a
if(this.isComponent&&"function"==typeof t){r=n
n=t
t=e
a=this.element}else a=o(this.element,e);(0,i.addEventListener)(this,a,t,n,r)},removeEventListener(e,t,n,r){let a
if(this.isComponent&&"function"==typeof t){n=t
t=e
a=this.element}else a=o(this.element,e);(0,i.removeEventListener)(this,a,t,n,r)}})
function o(e,t){let n
if("string"===typeof t){let i=e.querySelector(t)
if(null===i)throw new Error(`Called addEventListener with selector not found in DOM: ${t}`)
n=i}else(t instanceof Element&&t.nodeType||t instanceof Window)&&(n=t)
return n}}))
define("ember-lifeline/mixins/run",["exports","@ember/object/mixin","@ember/debug","ember-lifeline/run-task","ember-lifeline/poll-task","ember-lifeline/debounce-task"],(function(e,t,n,i,o,r){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
e.default=t.default.create({init(){this._super(...arguments)},runTask(e){let t=arguments.length>1&&void 0!==arguments[1]?arguments[1]:0
return(0,i.runTask)(this,e,t)},cancelTask(e){(0,i.cancelTask)(this,e)},scheduleTask(e,t){for(var n=arguments.length,o=new Array(n>2?n-2:0),r=2;r<n;r++)o[r-2]=arguments[r]
return(0,i.scheduleTask)(this,e,t,...o)},debounceTask(e){for(var t=arguments.length,n=new Array(t>1?t-1:0),i=1;i<t;i++)n[i-1]=arguments[i];(0,r.debounceTask)(this,e,...n)},cancelDebounce(e){(0,r.cancelDebounce)(this,e)},throttleTask(e,t){return(0,i.throttleTask)(this,e,t)},cancelThrottle(e){(0,i.cancelTask)(this,e)},pollTask(e,t){return(0,o.pollTask)(this,e,t)},cancelPoll(e){(0,o.cancelPoll)(this,e)}})}))
define("ember-lifeline/poll-task",["exports","ember","ember-lifeline/utils/get-task","@ember/destroyable"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e._setRegisteredPollers=function(e){o=e}
e.cancelPoll=s
e.pollTask=function(e,a){let u,d=arguments.length>2&&void 0!==arguments[2]?arguments[2]:c(),m=(0,n.default)(e,a,"pollTask"),p=()=>m.call(e,u),f=o.get(e)
if(!f){f=new Set
o.set(e,f);(0,i.registerDestructor)(e,function(e,t){return function(){t.forEach((t=>{s(e,t)}))}}(e,f))}f.add(d)
u=function(){if(r)return r()
return!t.default.testing}()?p:()=>{l[d]=p}
m.call(e,u)
return d}
e.queuedPollTasks=void 0
e.setShouldPoll=function(e){r=e}
let o=new WeakMap
let r,a=0
let l=e.queuedPollTasks=Object.create(null)
function s(e,t){let n,i=o.get(e)
n=t
void 0!==i&&i.delete(n)
delete l[n]}function c(){return a++}}))
define("ember-lifeline/run-task",["exports","@ember/debug","@ember/runloop","@ember/destroyable","ember-lifeline/utils/get-task"],(function(e,t,n,i,o){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e._setRegisteredTimers=function(e){a=e}
e.cancelTask=l
e.runTask=function(e,t){let i=arguments.length>2&&void 0!==arguments[2]?arguments[2]:0
if(e.isDestroying)return r
let a=(0,o.default)(e,t,"runTask"),l=s(e),c=(0,n.later)((()=>{l.delete(c)
a.call(e)}),i)
l.add(c)
return c}
e.scheduleTask=function(e,t,i){if(e.isDestroying)return r
let a,l=(0,o.default)(e,i,"scheduleTask"),c=s(e)
for(var u=arguments.length,d=new Array(u>3?u-3:0),m=3;m<u;m++)d[m-3]=arguments[m]
a=(0,n.schedule)(t,e,(function(){c.delete(a)
for(var t=arguments.length,n=new Array(t),i=0;i<t;i++)n[i]=arguments[i]
l.call(e,...n)}),...d)
c.add(a)
return a}
e.throttleTask=function(e,t){if(e.isDestroying)return r
for(var i=arguments.length,o=new Array(i>2?i-2:0),a=2;a<i;a++)o[a-2]=arguments[a]
const l=o[o.length-1]
"boolean"==typeof l&&o[o.length-2]
let c=s(e),u=(0,n.throttle)(e,t,...o)
c.add(u)
return u}
const r=-1
let a=new WeakMap
function l(e,t){s(e).delete(t);(0,n.cancel)(t)}function s(e){let t=a.get(e)
if(!t){t=new Set
a.set(e,t);(0,i.registerDestructor)(e,function(e,t){return function(){t.forEach((t=>{l(e,t)}))
t.clear()}}(e,t))}return t}}))
define("ember-lifeline/types/index",[],(function(){}))
define("ember-lifeline/utils/disposable",["exports","@ember/debug","@ember/destroyable"],(function(e,t,n){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.registerDisposable=function(e,t){(0,n.registerDestructor)(e,t)}
e.runDisposables=function(){}}))
define("ember-lifeline/utils/get-task",["exports"],(function(e){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=function(e,t,n){let i,o=typeof t
if("function"===o)i=t
else{if("string"!==o)throw new TypeError(`You must pass a task function or method name to '${n}'.`)
i=e[t]
if("function"!=typeof i)throw new TypeError(`The method name '${t}' passed to ${n} does not resolve to a valid function.`)}return i}}))
define("ember-lifeline/utils/get-timeout-or-test-fallback",["exports","ember"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.getTimeoutOrTestFallback=function(e){let{timeout:n,scaling:i=100}=arguments.length>1&&void 0!==arguments[1]?arguments[1]:{scaling:100}
if(t.default.testing)return void 0!==n?n:e/i
return e}}))
define("ember-test-waiters/index",["exports","@ember/debug","@ember/test-waiters"],(function(e,t,n){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
Object.keys(n).forEach((function(t){"default"!==t&&"__esModule"!==t&&(t in e&&e[t]===n[t]||Object.defineProperty(e,t,{enumerable:!0,get:function(){return n[t]}}))}))}))
define("msg-conversation-ui/components/connection-invitation-presenter",["exports","@babel/runtime/helpers/esm/initializerDefineProperty","@babel/runtime/helpers/esm/defineProperty","@babel/runtime/helpers/esm/applyDecoratedDescriptor","@babel/runtime/helpers/esm/initializerWarningHelper","@ember/template-factory","@ember/helper","@ember/component","@glimmer/component","@ember/service","@ember/object","@ember/destroyable","ember-cli-pemberly-i18n/helpers/t","artdeco-button/components/artdeco-button","ember-cli-pemberly-tracking/modifiers/track-interaction","hue-web-icons/components/icon","@ember/modifier"],(function(e,t,n,i,o,r,a,l,s,c,u,d,m,p,f,g,b){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var h,v,y,_,w,k,P,T,x,I,O
e.default=(0,l.setComponentTemplate)((0,r.createTemplateFactory)({id:"QCKMX5RK",block:'[[[1,"\\n"],[1,"    "],[10,0],[14,0,"msg-s-thread-actions-tray__item-nonconnection-banner msg-s-thread-actions-tray__item t-12 t-black t-normal"],[12],[1,"\\n      "],[10,0],[14,0,"msg-nonconnection-banner__primary-text flex-wrap mr2"],[12],[1,"\\n        "],[1,[52,[30,1,["hasPendingInvitationReceived"]],[28,[32,0],["i18n_requested_to_connect","msg-conversation-ui/components/connection-invitation-presenter"],[["participantName"],[[30,1,["participantName"]]]]],[28,[32,0],["i18n_not_connected","msg-conversation-ui/components/connection-invitation-presenter"],[["participantName"],[[30,1,["participantName"]]]]]]],[1,"\\n      "],[13],[1,"\\n\\n      "],[10,0],[14,0,"mlA flex-shrink-zero"],[12],[1,"\\n"],[41,[30,1,["hasPendingInvitationReceived"]],[[[1,"          "],[8,[32,1],[[4,[32,2],["click",[30,0,["declineConnection"]]],null]],[["@class","@type","@size","@circle","@color","@icon","@text"],["msg-nonconnection-banner__decline-btn mr1","secondary",1,true,"muted","close",[28,[32,0],["a11y_decline_connection_request","msg-conversation-ui/components/connection-invitation-presenter"],null]]],null],[1,"\\n\\n          "],[8,[32,1],[[4,[32,2],["click",[30,0,["acceptConnection"]]],null],[4,[32,3],["confirm_connection_invite"],null]],[["@class","@type","@size","@circle","@icon","@text"],["msg-nonconnection-banner__accept-btn","secondary",1,true,"check",[28,[32,0],["a11y_accept_connection_request","msg-conversation-ui/components/connection-invitation-presenter"],null]]],null],[1,"\\n"]],[]],[[[41,[30,1,["hasPendingInvitationSent"]],[[[1,"          "],[10,1],[14,0,"msg-nonconnection-banner__pending"],[12],[1,"\\n            "],[8,[32,4],[[24,0,"v-align-top"]],[["@a11yText","@name","@type","@size"],[[28,[32,0],["i18n_invitation_pending","msg-conversation-ui/components/connection-invitation-presenter"],null],"clock","system","small"]],null],[1,"\\n            "],[1,[28,[32,0],["i18n_invitation_pending","msg-conversation-ui/components/connection-invitation-presenter"],null]],[1,"\\n          "],[13],[1,"\\n"]],[]],[[[1,"          "],[8,[32,1],[[4,[32,2],["click",[30,0,["requestToConnect"]]],null],[4,[32,3],["send_connection_invite"],null]],[["@icon","@circle","@size","@type","@class","@text"],["connect",true,1,"secondary","msg-nonconnection-banner__connect-btn",[28,[32,0],["a11y_request_to_connect","msg-conversation-ui/components/connection-invitation-presenter"],null]]],null],[1,"\\n        "]],[]]]],[]]],[1,"      "],[13],[1,"\\n    "],[13],[1,"\\n  "]],["@viewData"],false,["if"]]',moduleName:"msg-conversation-ui/components/connection-invitation-presenter.gjs",scope:()=>[m.default,p.default,b.on,f.default,g.default],isStrictMode:!0}),(h=(0,c.inject)("i18n"),v=(0,c.inject)("global-services@a11y-notification"),y=(0,c.inject)("persistent-toast-manager@persistent-toast-manager"),_=(0,c.inject)("invitation-platform@invitation-platform"),w=(0,c.inject)("msg-data@data-manager"),k=class e extends s.default{constructor(){super(...arguments);(0,t.default)(this,"i18n",P,this);(0,t.default)(this,"a11yNotification",T,this);(0,t.default)(this,"persistentToastManager",x,this);(0,t.default)(this,"invitationPlatform",I,this);(0,t.default)(this,"msgDataManager",O,this)}acceptConnection(){this.invitationPlatform.acceptInvitation(this.args.viewData.pendingInvitation).then((()=>{this.isDestroying||this._removePendingInvitationFromConversation(!0)})).catch((e=>{if((0,d.isDestroying)(this))throw e
this._errorToast("i18n_accept_error")
throw e}))}declineConnection(){this.invitationPlatform.ignoreInvitation(this.args.viewData.pendingInvitation).then((()=>{(0,d.isDestroying)(this)||this._removePendingInvitationFromConversation(!1)})).catch((e=>{if((0,d.isDestroying)(this))throw e
this._errorToast("i18n_decline_error")
throw e}))}requestToConnect(){this.invitationPlatform.sendInvitationByProfileId({profileId:this.args.viewData.recipientProfileId}).then((()=>{this.isDestroying||this._a11yNotify("i18n_request_to_connect_is_pending",{participantName:this.args.viewData.participantName})})).catch((e=>{if((0,d.isDestroying)(this))throw e
this._errorToast("i18n_request_to_connect_error")
throw e}))}_errorToast(t){const n=this.i18n.lookupTranslation(e,t)()
this.persistentToastManager.error({message:n})}_a11yNotify(t,n){const i=this.i18n.lookupTranslation(e,t)
this.a11yNotification.setTextInLiveRegion(i([n]))}_removePendingInvitationFromConversation(e){this.msgDataManager.connectionStatusMap.set(this.args.viewData.recipientProfileUrn,{isConnected:e,pendingInvitation:null,invitationType:null})}},P=(0,i.default)(k.prototype,"i18n",[h],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),T=(0,i.default)(k.prototype,"a11yNotification",[v],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),x=(0,i.default)(k.prototype,"persistentToastManager",[y],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),I=(0,i.default)(k.prototype,"invitationPlatform",[_],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),O=(0,i.default)(k.prototype,"msgDataManager",[w],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),(0,i.default)(k.prototype,"acceptConnection",[u.action],Object.getOwnPropertyDescriptor(k.prototype,"acceptConnection"),k.prototype),(0,i.default)(k.prototype,"declineConnection",[u.action],Object.getOwnPropertyDescriptor(k.prototype,"declineConnection"),k.prototype),(0,i.default)(k.prototype,"requestToConnect",[u.action],Object.getOwnPropertyDescriptor(k.prototype,"requestToConnect"),k.prototype),k))}))
define("msg-conversation-ui/components/conversation-rename-presenter",["exports","@babel/runtime/helpers/esm/initializerDefineProperty","@babel/runtime/helpers/esm/defineProperty","@babel/runtime/helpers/esm/applyDecoratedDescriptor","@babel/runtime/helpers/esm/initializerWarningHelper","@ember/template-factory","@ember/component","msg-shared/utils/constants","@ember/object/internals","@glimmer/tracking","@glimmer/component","@ember/service","@ember/object","@ember/modifier","global-modifiers/modifiers/on-click-outside","ember-cli-pemberly-tracking/modifiers/track-render","ember-cli-pemberly-i18n/helpers/t","@ember/helper","global-modifiers/modifiers/focus","artdeco-button/components/artdeco-button"],(function(e,t,n,i,o,r,a,l,s,c,u,d,m,p,f,g,b,h,v,y){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var _,w,k,P,T,x,I,O,D,M
const{ESC:C}=l.KEYCODES
e.default=(0,a.setComponentTemplate)((0,r.createTemplateFactory)({id:"Lw7kw9S4",block:'[[[1,"\\n"],[1,"    "],[11,"form"],[24,0,"msg-s-thread-actions-tray__item msg-s-thread-actions-tray__item--rename"],[17,1],[4,[32,0],["submit",[30,0,["onFormSubmit"]]],null],[4,[32,0],["change",[30,0,["onFormChange"]]],null],[4,[32,0],["keyup",[30,0,["onFormKeyUp"]]],null],[4,[32,1],[[30,2]],null],[4,[32,2],null,[["pageKey","routeName","currentRoute"],[[30,3],[28,[32,3],[[53,"outletState"],"render.name"],null],[28,[32,3],[[53,"outletState"],"render"],null]]]],[12],[1,"\\n      "],[10,"label"],[14,0,"visually-hidden"],[15,"for",[29,["msg-s-thread-actions-tray__rename-input-",[30,0,["elementId"]]]]],[12],[1,"\\n        "],[1,[28,[32,4],["i18n_name_conversation","msg-conversation-ui/components/conversation-rename-presenter"],null]],[1,"\\n      "],[13],[1,"\\n      "],[11,"input"],[16,1,[28,[32,5],["msg-s-thread-actions-tray__rename-input-",[30,0,["elementId"]]],null]],[24,0,"msg-s-thread-actions-tray__rename-input t-20 t-black t-light"],[16,2,[30,4,["conversationName"]]],[16,"placeholder",[28,[32,4],["i18n_name_conversation","msg-conversation-ui/components/conversation-rename-presenter"],null]],[24,4,"text"],[4,[32,6],null,null],[12],[13],[1,"\\n      "],[8,[32,7],null,[["@class","@controlType","@size","@disabled"],["ml2 flex-shrink-zero","submit",1,[30,0,["disableSaveButton"]]]],[["default"],[[[[1,"\\n        "],[1,[28,[32,4],["i18n_save","msg-conversation-ui/components/conversation-rename-presenter"],null]],[1,"\\n      "]],[]]]]],[1,"\\n    "],[13],[1,"\\n  "]],["&attrs","@hideRenameConversationForm","@pageKey","@viewData"],false,["-get-dynamic-var"]]',moduleName:"msg-conversation-ui/components/conversation-rename-presenter.gjs",scope:()=>[p.on,f.default,g.default,h.get,b.default,h.concat,v.default,y.default],isStrictMode:!0}),(_=(0,d.inject)("msg-data@data-manager"),w=(0,d.inject)("tracking"),k=(0,d.inject)("i18n"),P=(0,d.inject)("global-services@a11y-notification"),T=class e extends u.default{constructor(){super(...arguments);(0,t.default)(this,"msgDataManager",x,this);(0,t.default)(this,"tracking",I,this);(0,t.default)(this,"i18n",O,this);(0,t.default)(this,"a11yNotification",D,this);(0,n.default)(this,"elementId",(0,s.guidFor)(this));(0,t.default)(this,"internalConversationName",M,this)}get invalidLength(){return this.internalConversationName.length>l.RENAME_MAX_CHARACTERS}get disableSaveButton(){return!!this.invalidLength||!(0!==this.internalConversationName.length||!this.args.viewData.disableRemovingName)}onFormKeyUp(e){if(e.keyCode===C){e.stopPropagation()
this.args.hideRenameConversationForm()}}onFormSubmit(t){t.preventDefault()
this.tracking.fireInteractionEvent(`${this.args.actionTrackingPrefix||""}save_rename`)
if(!this.invalidLength){var n,i,o
const r=this.args.viewData.conversationName||"",a=this.internalConversationName?this.internalConversationName.trim():""
let l
if(r!==a){this.msgDataManager.updateConversationName(this.args.viewData.conversationEntityUrn,a)
l=this.i18n.lookupTranslation(e,"i18n_a11y_renamed_announcement")([{conversationName:a}])}else l=this.i18n.lookupTranslation(e,"i18n_a11y_rename_closed_announcement")([])
this.args.hideRenameConversationForm()
this.a11yNotification.setTextInLiveRegion(l)
null==t||null===(n=t.target)||void 0===n||null===(i=n.closest(".msg-convo-wrapper"))||void 0===i||null===(o=i.querySelector(".msg-thread-actions__control"))||void 0===o||o.focus()}}onFormChange(e){this.internalConversationName=e.target.value
this.tracking.fireInteractionEvent(`${this.args.actionTrackingPrefix||""}group_chat_name`)}},x=(0,i.default)(T.prototype,"msgDataManager",[_],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),I=(0,i.default)(T.prototype,"tracking",[w],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),O=(0,i.default)(T.prototype,"i18n",[k],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),D=(0,i.default)(T.prototype,"a11yNotification",[P],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),M=(0,i.default)(T.prototype,"internalConversationName",[c.tracked],{configurable:!0,enumerable:!0,writable:!0,initializer:function(){return this.args.viewData.conversationName||""}}),(0,i.default)(T.prototype,"onFormKeyUp",[m.action],Object.getOwnPropertyDescriptor(T.prototype,"onFormKeyUp"),T.prototype),(0,i.default)(T.prototype,"onFormSubmit",[m.action],Object.getOwnPropertyDescriptor(T.prototype,"onFormSubmit"),T.prototype),(0,i.default)(T.prototype,"onFormChange",[m.action],Object.getOwnPropertyDescriptor(T.prototype,"onFormChange"),T.prototype),T))}))
define("msg-conversation-ui/components/inmail-credits-presenter",["exports","@ember/template-factory","@ember/component/template-only","@ember/component","ember-cli-pemberly-i18n/helpers/t","hue-web-icons/components/icon","global-helpers/helpers/or","@ember/helper","msg-ui/components/hiring-pro-badge"],(function(e,t,n,i,o,r,a,l,s){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
const c=(0,i.setComponentTemplate)((0,t.createTemplateFactory)({id:"TGxKwzTA",block:'[[[1,"\\n"],[1,"  "],[10,"section"],[15,0,[29,["msg-inmail-credits-display pv2 ph4 relative\\n      ",[52,[30,1],"justify-flex-end"]]]],[12],[1,"\\n"],[41,[51,[30,1]],[[[41,[30,2],[[[1,"        "],[8,[32,0],null,null,null],[1,"\\n"]],[]],[[[1,"        "],[10,1],[14,0,"a11y-text"],[12],[1,"\\n          "],[1,[28,[32,1],["i18n_a11y_premium_badge","msg-conversation-ui/components/inmail-credits-presenter"],null]],[1,"\\n        "],[13],[1,"\\n        "],[8,[32,2],null,[["@type","@size","@name","@a11yText"],["logo","xxxsmall","premium-badge","Premium"]],null],[1,"\\n"]],[]]]],[]],null],[1,"    "],[10,2],[14,0,"t-12 t-black--light t-normal"],[12],[1,"\\n"],[41,[30,3],[[[1,"        "],[1,[28,[32,1],["i18n_loading_indicator","msg-conversation-ui/components/inmail-credits-presenter"],null]],[1,"\\n"]],[]],[[[41,[28,[32,3],[[30,4],[30,1]],null],[[[1,"        "],[1,[28,[32,1],["i18n_free_inmail_with_why_link","msg-conversation-ui/components/inmail-credits-presenter"],[["linkInfo"],[[28,[32,4],null,[["target","href","rel","class","aria-label","data-control-name","data-test-awaiting-inmail-response-learn-more"],["_blank","/help/linkedin/answer/139","noopener noreferrer","link",[28,[32,1],["i18n_free_inmail_why_a11y","msg-conversation-ui/components/inmail-credits-presenter"],null],"free_inmail_why",true]]]]]]],[1,"\\n"]],[]],[[[41,[30,5],[[[41,[30,2],[[[1,"          "],[10,1],[12],[1,"\\n            "],[1,[28,[32,1],["i18n_hero_candidate_sourcing_credits","msg-conversation-ui/components/inmail-credits-presenter"],[["numCredits"],[[30,5]]]]],[1,"\\n          "],[13],[1,"\\n"]],[]],[[[1,"          "],[10,1],[12],[1,"\\n            "],[1,[28,[32,1],["i18n_num_credits_left","msg-conversation-ui/components/inmail-credits-presenter"],[["numCredits"],[[30,5]]]]],[1,"\\n          "],[13],[1,"\\n"]],[]]]],[]],[[[1,"        "],[10,1],[14,0,"msg-inmail-credits-display__error"],[12],[1,"\\n          "],[1,[28,[32,1],["i18n_no_credits_left","msg-conversation-ui/components/inmail-credits-presenter"],null]],[1,"\\n        "],[13],[1,"\\n      "]],[]]]],[]]]],[]]],[1,"    "],[13],[1,"\\n  "],[13],[1,"\\n"]],["@recipientOpenToFreeMessages","@isHeroCandidateSourcing","@loading","@isOpenLink","@inmailCredits"],false,["if","unless"]]',moduleName:"msg-conversation-ui/components/inmail-credits-presenter.gjs",scope:()=>[s.default,o.default,r.default,a.default,l.hash],isStrictMode:!0}),(0,n.default)("inmail-credits-presenter","InmailCreditsPresenter"))
e.default=c}))
define("msg-conversation-ui/components/premium-custom-cta-presenter",["exports","@ember/template-factory","@ember/helper","@ember/component/template-only","@ember/component","text-view-model/components/text-view-model-v2","ember-cli-pemberly-tracking/modifiers/track-render","ember-cli-pemberly-tracking/modifiers/track-interaction","ember-cli-pemberly-tracking/modifiers/track-view","ember-cli-pemberly-tracking/components/shared/external-link"],(function(e,t,n,i,o,r,a,l,s,c){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
const u=(0,o.setComponentTemplate)((0,t.createTemplateFactory)({id:"J+mjJ7VY",block:'[[[1,"\\n  "],[8,[32,0],[[24,"data-view-name","premium-custom-button-on-messaging"],[4,[32,1],null,[["pageKey","routeName","currentRoute"],["flagship3_messaging_premium_custom_button_banner",[28,[32,2],[[53,"outletState"],"render.name"],null],[28,[32,2],[[53,"outletState"],"render"],null]]]],[4,[32,3],["click_premium_custom_button_banner_action"],null],[4,[32,4],null,[["viewName","contentTrackingId","routeName","currentRoute"],["premium-custom-button-on-messaging",[30,1,["trackingId"]],[28,[32,2],[[53,"outletState"],"render.name"],null],[28,[32,2],[[53,"outletState"],"render"],null]]]]],[["@href","@target","@class"],[[30,1,["targetUrl"]],"_blank","msg-s-thread-actions-tray__item msg-s-thread-actions-tray__item--custom-cta-blue t-12 t-bold"]],[["default"],[[[[1,"\\n    "],[8,[32,5],null,[["@tvm"],[[30,1,["title"]]]],null],[1,"\\n  "]],[]]]]],[1,"\\n"]],["@composeViewHeader"],false,["-get-dynamic-var"]]',moduleName:"msg-conversation-ui/components/premium-custom-cta-presenter.gjs",scope:()=>[c.default,a.default,n.get,l.default,s.default,r.default],isStrictMode:!0}),(0,i.default)("premium-custom-cta-presenter","PremiumCustomCtaPresenter"))
e.default=u}))
define("msg-conversation-ui/components/premium/premium-footer-presenter",["exports","@ember/template-factory","@ember/helper","@ember/component","@glimmer/component","feature-introduction/components/label","text-view-model/components/text-view-model-v2","image-view-model/components/image-view-model","ember-cli-pemberly-tracking/modifiers/track-view"],(function(e,t,n,i,o,r,a,l,s){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
const c={PREMIUM_INMAIL_FOLLOW_UP_FOOTER:"premium-inmail-follow-up-banner"}
class u extends o.default{get showNewLabel(){return"NEW_BADGE"===this.args.composeViewFooter.badge}get viewName(){return c[this.args.composeViewFooter.type]??""}}e.default=u;(0,i.setComponentTemplate)((0,t.createTemplateFactory)({id:"eCG2XwVp",block:'[[[1,"\\n    "],[11,0],[24,0,"msg-s-conversation-premium-footer"],[16,"data-view-name",[30,0,["viewName"]]],[4,[32,0],null,[["viewName","contentTrackingId","routeName","currentRoute"],[[30,0,["viewName"]],[30,1,["trackingId"]],[28,[32,1],[[53,"outletState"],"render.name"],null],[28,[32,1],[[53,"outletState"],"render"],null]]]],[12],[1,"\\n      "],[10,0],[14,0,"display-flex align-items-center"],[12],[1,"\\n"],[41,[30,1,["icon"]],[[[1,"          "],[8,[32,2],[[24,0,"msg-s-conversation-premium-footer__badge"]],[["@images"],[[30,1,["icon"]]]],null],[1,"\\n"]],[]],null],[41,[30,0,["showNewLabel"]],[[[1,"          "],[8,[32,3],[[24,0,"msg-s-conversation-premium-footer__badge"]],null,null],[1,"\\n"]],[]],null],[1,"      "],[13],[1,"\\n      "],[10,2],[14,0,"t-12 t-black"],[12],[1,"\\n        "],[8,[32,4],null,[["@tvm"],[[30,1,["title"]]]],null],[1,"\\n      "],[13],[1,"\\n    "],[13],[1,"\\n  "]],["@composeViewFooter"],false,["-get-dynamic-var","if"]]',moduleName:"msg-conversation-ui/components/premium/premium-footer-presenter.gts",scope:()=>[s.default,n.get,l.default,r.default,a.default],isStrictMode:!0}),u)}))
define("msg-conversation-ui/components/profile-social-nudge-verification-footer-presenter",["exports","@babel/runtime/helpers/esm/initializerDefineProperty","@babel/runtime/helpers/esm/defineProperty","@babel/runtime/helpers/esm/applyDecoratedDescriptor","@babel/runtime/helpers/esm/initializerWarningHelper","@ember/template-factory","@ember/helper","@ember/component","@glimmer/component","artdeco-inline-feedback/components/artdeco-inline-feedback","text-view-model/components/text-view-model-v2","@ember/object","ember-cli-pemberly-i18n/helpers/t","@ember/modifier","@glimmer/tracking","ember-cli-pemberly-tracking/modifiers/track-render","ember-cli-pemberly-tracking/modifiers/track-view","lego/utils/constants","artdeco-button/components/artdeco-button","@ember/service","msg-data/utils/sdk-view-data-helpers"],(function(e,t,n,i,o,r,a,l,s,c,u,d,m,p,f,g,b,h,v,y,_){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var w,k,P,T,x,I,O,D,M,C,S,j
e.default=(0,l.setComponentTemplate)((0,r.createTemplateFactory)({id:"Di4Kryfk",block:'[[[1,"\\n"],[41,[30,0,["showFooter"]],[[[1,"      "],[11,0],[24,0,"msg-s-conversation-blocked-footer msg-s-conversation-blocked-footer--with-dismiss msg-s-conversation-blocked-footer--reduced-padding"],[4,[32,0],null,[["onRender","routeName","currentRoute"],[[30,0,["onLegoImpression"]],[28,[32,1],[[53,"outletState"],"render.name"],null],[28,[32,1],[[53,"outletState"],"render"],null]]]],[12],[1,"\\n        "],[8,[32,2],[[24,0,"flex-1"]],[["@type"],["note"]],[["default"],[[[[1,"\\n          "],[8,[32,3],null,[["@tvm"],[[30,1,["title"]]]],null],[10,"br"],[12],[13],[1,"\\n          "],[11,3],[24,6,"#"],[24,0,"link-without-hover-visited"],[24,"data-view-name","request-verify-now"],[4,[32,4],null,[["viewName","actionCategory","view","routeName","currentRoute"],["request-verify-now","CLICK_REQUEST_VERIFY",[30,0],[28,[32,1],[[53,"outletState"],"render.name"],null],[28,[32,1],[[53,"outletState"],"render"],null]]]],[4,[32,5],["click",[30,0,["requestVerification"]]],null],[12],[1,[28,[32,6],["i18n_request_now","msg-conversation-ui/components/profile-social-nudge-verification-footer-presenter"],null]],[13],[1,"\\n        "]],[]]]]],[1,"\\n        "],[8,[32,7],[[24,0,"msg-s-conversation-blocked-footer__dismiss"],[4,[32,5],["click",[30,0,["dismissFooter"]]],null]],[["@text","@type","@color","@size","@circle","@icon"],[[28,[32,6],["i18n_dismiss","msg-conversation-ui/components/profile-social-nudge-verification-footer-presenter"],null],"tertiary","muted",1,true,"close"]],null],[1,"\\n      "],[13],[1,"\\n"]],[]],null],[1,"  "]],["@composeViewFooter"],false,["if","-get-dynamic-var"]]',moduleName:"msg-conversation-ui/components/profile-social-nudge-verification-footer-presenter.gjs",scope:()=>[g.default,a.get,c.default,u.default,b.default,p.on,m.default,v.default],isStrictMode:!0}),(w=(0,y.inject)("persistent-toast-manager@persistent-toast-manager"),k=(0,y.inject)("tracking"),P=(0,y.inject)("lego@tracking"),T=(0,y.inject)("i18n"),x=(0,y.inject)("authentication@authenticated-user"),I=class e extends s.default{constructor(){super(...arguments);(0,t.default)(this,"persistentToastManager",O,this);(0,t.default)(this,"tracking",D,this);(0,t.default)(this,"legoTracking",M,this);(0,t.default)(this,"i18n",C,this);(0,t.default)(this,"authenticatedUser",S,this);(0,t.default)(this,"showFooter",j,this)}get sender(){const e=(0,_.getNonSelfParticipants)(this.args.conversation.decoratedParticipants,this.authenticatedUser.miniProfile)[0]
return{lastName:e.lastName,firstName:e.firstName}}get contentTrackingId(){return this.args.composeViewFooter.trackingId}onLegoImpression(){this.args.composeViewFooter.legoTrackingId&&this.legoTracking.sendLegoImpression(this.args.composeViewFooter.legoTrackingId,h.LEGO_IMPRESSION_VISIBILITY_SHOW)
return[]}requestVerification(){this.showFooter=!1
const t=this.i18n.lookupTranslation(e,"i18n_request_sent")({member:this.sender})
this.persistentToastManager.success({message:t})
this.tracking.fireTrackingPayload("MessagingFooterActionClickEvent",{trackingId:this.args.composeViewFooter.trackingId})
this.args.composeViewFooter.legoTrackingId&&this.legoTracking.sendLegoAction(this.args.composeViewFooter.legoTrackingId,this.legoTracking.LEGO_ACTION_PRIMARY)}dismissFooter(){this.showFooter=!1
this.args.composeViewFooter.legoTrackingId&&this.legoTracking.sendLegoAction(this.args.composeViewFooter.legoTrackingId,this.legoTracking.LEGO_ACTION_DISMISS)}},O=(0,i.default)(I.prototype,"persistentToastManager",[w],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),D=(0,i.default)(I.prototype,"tracking",[k],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),M=(0,i.default)(I.prototype,"legoTracking",[P],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),C=(0,i.default)(I.prototype,"i18n",[T],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),S=(0,i.default)(I.prototype,"authenticatedUser",[x],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),j=(0,i.default)(I.prototype,"showFooter",[f.tracked],{configurable:!0,enumerable:!0,writable:!0,initializer:function(){return!0}}),(0,i.default)(I.prototype,"onLegoImpression",[d.action],Object.getOwnPropertyDescriptor(I.prototype,"onLegoImpression"),I.prototype),(0,i.default)(I.prototype,"requestVerification",[d.action],Object.getOwnPropertyDescriptor(I.prototype,"requestVerification"),I.prototype),(0,i.default)(I.prototype,"dismissFooter",[d.action],Object.getOwnPropertyDescriptor(I.prototype,"dismissFooter"),I.prototype),I))}))
define("msg-conversation-ui/components/profile-verification-footer-presenter",["exports","@babel/runtime/helpers/esm/initializerDefineProperty","@babel/runtime/helpers/esm/defineProperty","@babel/runtime/helpers/esm/applyDecoratedDescriptor","@babel/runtime/helpers/esm/initializerWarningHelper","@ember/template-factory","@ember/component","@glimmer/component","artdeco-inline-feedback/components/artdeco-inline-feedback","text-view-model/components/text-view-model-v2","@glimmer/tracking"],(function(e,t,n,i,o,r,a,l,s,c,u){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var d,m
e.default=(0,a.setComponentTemplate)((0,r.createTemplateFactory)({id:"My39J2eI",block:'[[[1,"\\n"],[41,[30,0,["shouldShowSavedFooter"]],[[[1,"      "],[10,0],[14,0,"msg-s-conversation-blocked-footer"],[12],[1,"\\n        "],[8,[32,0],null,[["@type"],["note"]],[["default"],[[[[1,"\\n          "],[8,[32,1],null,[["@tvm"],[[30,0,["savedFooterTitle"]]]],null],[1,"\\n        "]],[]]]]],[1,"\\n      "],[13],[1,"\\n"]],[]],null],[1,"  "]],[],false,["if"]]',moduleName:"msg-conversation-ui/components/profile-verification-footer-presenter.gjs",scope:()=>[s.default,c.default],isStrictMode:!0}),(d=class extends l.default{constructor(){super(...arguments);(0,t.default)(this,"savedComposeViewFooter",m,this)
this.args.composeViewFooter&&(this.savedComposeViewFooter=this.args.composeViewFooter)}get currentFooterTitle(){var e
return null===(e=this.args.composeViewFooter)||void 0===e?void 0:e.title}get savedFooterTitle(){var e
return null===(e=this.savedComposeViewFooter)||void 0===e?void 0:e.title}get shouldShowSavedFooter(){var e
return this.savedComposeViewFooter&&(null===(e=this.args.conversation)||void 0===e?void 0:e.backendUrn)}},m=(0,i.default)(d.prototype,"savedComposeViewFooter",[u.tracked],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),d))}))
define("msg-conversation-ui/components/recipient-detail-group-presenter",["exports","@babel/runtime/helpers/esm/applyDecoratedDescriptor","@ember/template-factory","@ember/helper","@ember/component","global-utils/utils/get-location","@glimmer/component","@ember/object","artdeco-entity-pile/components/artdeco-entity-pile","presence/components/entity-with-presence-presenter","global-helpers/helpers/eq","ember-cli-pemberly-i18n/helpers/t","global-helpers/helpers/lt","global-helpers/helpers/gt","ember-cli-pemberly-i18n/helpers/format-name","artdeco-button/components/artdeco-button","ember-cli-pemberly-tracking/modifiers/track-interaction","@ember/modifier","ember-set-helper/helpers/set","app-aware-link/components/app-aware-link","image-view-model/components/image-view-model","@ember/render-modifiers/modifiers/did-insert","text-view-model/helpers/text-view-model","msg-shared-modals/components/conversation-modals-presenter","msg-ui/components/primitives/profile-badge","text-view-model/components/text-view-model-v2","global-helpers/helpers/sub"],(function(e,t,n,i,o,r,a,l,s,c,u,d,m,p,f,g,b,h,v,y,_,w,k,P,T,x,I){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var O
e.default=(0,o.setComponentTemplate)((0,n.createTemplateFactory)({id:"upBVW8zr",block:'[[[1,"\\n"],[1,"    "],[10,0],[15,0,[29,["msg-s-profile-card ph3 ",[30,1]]]],[12],[1,"\\n      "],[8,[32,0],null,[["@entities","@size","@maxEntities","@shape","@stacked","@onEntityClick","@disableIndividualTouchTargets"],[[30,2,["recipientProfiles"]],4,5,"circle",false,[30,0,["openProfile"]],true]],[["default"],[[[[1,"\\n        "],[8,[32,1],[[24,0,"msg-conversation-card__presence-entity"]],[["@viewData","@size","@makeImageFocusable"],[[30,3,["entityWithPresenceViewData"]],4,true]],null],[1,"\\n      "]],[3]]]]],[1,"\\n\\n"],[41,[30,2,["title"]],[[[1,"        "],[10,0],[14,0,"text-body-medium-bold pt2"],[12],[1,"\\n          "],[1,[30,2,["title"]]],[1,"\\n        "],[13],[1,"\\n"]],[]],[[[1,"        "],[10,0],[14,0,"mt2 t-14 t-bold"],[12],[1,"\\n"],[42,[28,[31,2],[[28,[31,2],[[30,2,["recipientProfiles"]]],null]],null],null,[[[41,[28,[32,2],[[30,5],4],null],[[[1,"                "],[10,1],[12],[1,"\\n                  "],[8,[32,3],[[24,0,"inline-block v-align-middle"]],[["@href"],[[30,4,["participantProfileUrl"]]]],[["default"],[[[[1,"\\n                    "],[10,1],[12],[1,"\\n                      "],[1,[28,[32,4],null,[["firstName","lastName","type"],[[30,4,["name","firstName"]],[30,4,["name","lastName"]],"full"]]]],[1,"\\n                    "],[13],[1,"\\n                  "]],[]]]]],[1,"\\n                  "],[8,[32,5],null,[["@memberBadgeType"],[[30,4,["memberBadgeType"]]]],null],[1,"\\n                "],[13],[1,"\\n                "],[10,1],[14,0,"inline-block v-align-middle"],[12],[1,"\\n                  "],[41,[28,[32,6],[[30,2,["recipientProfiles","length"]],1],null],[[],[]],[[[41,[28,[32,6],[[30,5],[28,[32,7],[[30,2,["recipientProfiles","length"]],1],null]],null],[[],[]],[[[41,[28,[32,6],[[30,2,["recipientProfiles","length"]],2],null],[[[1,"\\n                    "],[41,[28,[32,6],[[30,5],0],null],[[[1,[28,[32,8],["i18n_and","msg-conversation-ui/components/recipient-detail-group-presenter"],null]]],[]],null],[1,"\\n"]],[]],[[[41,[28,[32,6],[[30,2,["recipientProfiles","length"]],3],null],[[[1,"                    "],[41,[28,[32,6],[[30,5],1],null],[[[1,", "],[1,[28,[32,8],["i18n_and","msg-conversation-ui/components/recipient-detail-group-presenter"],null]]],[]],[[[1,","]],[]]],[1,"\\n"]],[]],[[[41,[28,[32,6],[[30,2,["recipientProfiles","length"]],4],null],[[[1,"                    "],[41,[28,[32,6],[[30,5],2],null],[[[1,", "],[1,[28,[32,8],["i18n_and","msg-conversation-ui/components/recipient-detail-group-presenter"],null]]],[]],[[[1,","]],[]]],[1,"\\n"]],[]],[[[1,"                    "],[41,[28,[32,2],[[30,5],3],null],[[[1,","]],[]],null],[1,"\\n                  "]],[]]]],[]]]],[]]]],[]]]],[]]],[1,"\\n                "],[13],[1,"\\n"]],[]],null]],[4,5]],null],[41,[28,[32,9],[[30,0,["othersCount"]],0],null],[[[1,"              "],[10,1],[14,0,"inline-block"],[12],[1,"\\n                "],[1,[28,[32,8],["i18n_and_others","msg-conversation-ui/components/recipient-detail-group-presenter"],[["othersCount"],[[30,0,["othersCount"]]]]]],[1,"\\n              "],[13],[1,"\\n"]],[]],null],[1,"        "],[13],[1,"\\n"]],[]]],[1,"\\n"],[41,[30,2,["allowAddParticipant"]],[[[1,"        "],[10,0],[12],[1,"\\n          "],[8,[32,10],[[16,"aria-label",[28,[32,8],["i18n_invite_others_to_join","msg-conversation-ui/components/recipient-detail-group-presenter"],null]],[4,[32,11],[[52,[30,6],"overlay.invite_others_join","invite_others_join"]],null],[4,[32,12],["click",[28,[32,13],[[30,0],"isConvoDetailModalOpen",true],null]],null]],[["@class","@text","@type"],["msg-conversation-card__cta-button link-without-visited-state p0",[28,[32,8],["i18n_invite_others_to_join","msg-conversation-ui/components/recipient-detail-group-presenter"],null],"tertiary"]],null],[1,"\\n        "],[13],[1,"\\n"]],[]],[[[41,[30,2,["allowRenameConversation"]],[[[1,"        "],[10,0],[12],[1,"\\n          "],[8,[32,10],[[16,"aria-label",[28,[32,8],["i18n_rename_chat","msg-conversation-ui/components/recipient-detail-group-presenter"],null]],[4,[32,11],[[52,[30,6],"overlay.rename_chat_cta","rename_chat_cta"]],null],[4,[32,12],["click",[30,0,["openRenameConversationForm"]]],null]],[["@class","@text","@type"],["msg-conversation-card__cta-button link-without-visited-state p0",[28,[32,8],["i18n_rename_chat","msg-conversation-ui/components/recipient-detail-group-presenter"],null],"tertiary"]],null],[1,"\\n        "],[13],[1,"\\n      "]],[]],null]],[]]],[1,"\\n"],[41,[30,2,["headlineText"]],[[[1,"        "],[10,0],[14,0,"display-flex align-items-center mt2"],[12],[1,"\\n"],[41,[30,2,["headlineImage"]],[[[1,"            "],[8,[32,3],null,[["@href"],[[30,2,["headlineImage","actionTarget"]]]],[["default"],[[[[1,"\\n              "],[8,[32,14],[[24,0,"pr2"]],[["@entitySize","@images"],[3,[30,2,["headlineImage"]]]],null],[1,"\\n            "]],[]]]]],[1,"\\n"]],[]],null],[1,"          "],[11,0],[24,0,"t-12 t-normal t-black--light"],[4,[32,15],[[30,0,["makeHyperlinksOpenExternally"]]],null],[12],[1,"\\n            "],[1,[28,[32,16],[[30,2,["headlineText"]]],null]],[1,"\\n          "],[13],[1,"\\n        "],[13],[1,"\\n"]],[]],null],[1,"\\n"],[41,[30,2,["conversationDescription"]],[[[1,"        "],[10,2],[14,0,"msg-conversation-card__conversation-description"],[12],[1,"\\n          "],[8,[32,17],null,[["@tvm"],[[30,2,["conversationDescription"]]]],null],[1,"\\n        "],[13],[1,"\\n"]],[]],null],[1,"\\n      "],[8,[32,18],null,[["@viewData","@isConvoDetailModalOpen","@closeConvoDetailModal","@toggleConversationMute","@trackingModuleName","@actionTrackingPrefix","@addParticipantsPageKey","@isOverlay","@afterDismissFocusElement"],[[30,2,["conversationModalsViewData"]],[30,0,["isConvoDetailModalOpen"]],[28,[32,13],[[30,0],"isConvoDetailModalOpen",false],null],[30,7],[30,8],[30,9],[30,10],[30,6],[30,0,["rollupButtonElement"]]]],null],[1,"\\n    "],[13],[1,"\\n  "]],["@classNames","@viewData","profile","profile","index","@isOverlay","@toggleConversationMute","@trackingModuleName","@actionTrackingPrefix","@addParticipantsPageKey"],false,["if","each","-track-array"]]',moduleName:"msg-conversation-ui/components/recipient-detail-group-presenter.gjs",scope:()=>[s.default,c.default,m.default,y.default,f.default,T.default,u.default,I.default,d.default,p.default,g.default,b.default,h.on,v.default,_.default,w.default,k.default,x.default,P.default],isStrictMode:!0}),(O=class extends a.default{get othersCount(){return this.args.viewData.recipientProfiles.length-5+1}openRenameConversationForm(e){var t,n
e.stopPropagation()
null===(t=(n=this.args).toggleShowRenameConversation)||void 0===t||t.call(n,!0)}openProfile(e){(0,r.default)().assign(jSecure.sanitizeUrl(e.participantProfileUrl))}makeHyperlinksOpenExternally(e){this.args.isOverlay&&e.querySelectorAll("a").forEach((e=>e.setAttribute("target","_blank")))}},(0,t.default)(O.prototype,"openRenameConversationForm",[l.action],Object.getOwnPropertyDescriptor(O.prototype,"openRenameConversationForm"),O.prototype),(0,t.default)(O.prototype,"openProfile",[l.action],Object.getOwnPropertyDescriptor(O.prototype,"openProfile"),O.prototype),(0,t.default)(O.prototype,"makeHyperlinksOpenExternally",[l.action],Object.getOwnPropertyDescriptor(O.prototype,"makeHyperlinksOpenExternally"),O.prototype),O))}))
define("msg-conversation-ui/components/recipient-detail-one-to-one-presenter",["exports","@babel/runtime/helpers/esm/initializerDefineProperty","@babel/runtime/helpers/esm/defineProperty","@babel/runtime/helpers/esm/applyDecoratedDescriptor","@babel/runtime/helpers/esm/initializerWarningHelper","@ember/template-factory","@ember/helper","@ember/component","@glimmer/component","artdeco-entity-lockup/components/artdeco-entity-lockup","presence/components/entity-with-presence-presenter","ember-cli-pemberly-tracking/components/shared/external-link","ember-vector-images/components/lazy-image","app-aware-link/components/app-aware-link","pronouns/components/pronouns","ember-cli-pemberly-i18n/helpers/t","text-view-model/components/text-view-model-v2","global-helpers/helpers/attributed-text-html","msg-ui/components/primitives/profile-badge","artdeco-hoverables/components/artdeco-hoverable-trigger","artdeco-button/components/artdeco-button","@ember/service","@ember/object","@ember/modifier","global-utils/utils/url"],(function(e,t,n,i,o,r,a,l,s,c,u,d,m,p,f,g,b,h,v,y,_,w,k,P,T){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var x,I,O
e.default=(0,l.setComponentTemplate)((0,r.createTemplateFactory)({id:"kF7jnFmK",block:'[[[1,"\\n"],[1,"    "],[11,0],[24,0,"msg-s-profile-card msg-s-profile-card-one-to-one"],[17,1],[12],[1,"\\n      "],[8,[32,0],null,[["@class","@size","@stacked"],["break-words",[52,[30,2],"4","5"],[52,[30,2],false,"left"]]],[["default"],[[[[1,"\\n\\n"],[41,[30,0,["profileNavigationEnabled"]],[[[1,"          "],[8,[32,1],null,[["@href"],[[30,4,["recipientProfileUrl"]]]],[["default"],[[[[1,"\\n            "],[8,[30,3,["image"]],null,[["@type"],[[52,[30,4,["isRecipientOrganization"]],"square","circle"]]],[["default"],[[[[1,"\\n"],[41,[30,4,["isRecipientOrganization"]],[[[1,"                "],[8,[32,2],null,[["@class","@image","@alt","@ghostType","@desiredWidth","@desiredHeight","@ariaRole"],[[29,["presence-entity__image presence-entity__organization-image EntityPhoto-square-",[52,[30,2],4,5]]],[30,4,["pageLogo"]],[28,[32,3],["a11y_profile","msg-conversation-ui/components/recipient-detail-one-to-one-presenter"],[["name"],[[30,4,["participantName"]]]]],"company",[30,0,["pageLogoPixelSize"]],[30,0,["pageLogoPixelSize"]],"presentation"]],null],[1,"\\n"]],[]],[[[1,"                "],[8,[32,4],[[24,0,"msg-conversation-card__presence-entity"]],[["@viewData","@canShowSponsoredMemeberSenderProfileTooltip","@a11yText","@size"],[[30,4,["entityWithPresenceViewData"]],[30,0,["canShowSponsoredMemeberSenderProfileTooltip"]],[28,[32,3],["a11y_profile","msg-conversation-ui/components/recipient-detail-one-to-one-presenter"],[["name"],[[30,4,["participantName"]]]]],[52,[30,2],4,5]]],null],[1,"\\n"]],[]]],[1,"            "]],[]]]]],[1,"\\n          "]],[]]]]],[1,"\\n"]],[]],[[[1,"          "],[8,[30,3,["image"]],null,[["@type"],["circle"]],[["default"],[[[[1,"\\n            "],[8,[32,4],[[24,0,"msg-conversation-card__presence-entity"]],[["@viewData","@canShowSponsoredMemeberSenderProfileTooltip","@size"],[[30,4,["entityWithPresenceViewData"]],[30,0,["canShowSponsoredMemeberSenderProfileTooltip"]],[52,[30,2],4,5]]],null],[1,"\\n          "]],[]]]]],[1,"\\n"]],[]]],[1,"        "],[8,[30,3,["content"]],[[24,0,"overflow-hidden"]],null,[["default"],[[[[1,"\\n          "],[8,[30,3,["title"]],[[24,0,"display-flex truncate align-items-center"]],null,[["default"],[[[[1,"\\n\\n"],[41,[30,0,["profileNavigationEnabled"]],[[[1,"              "],[10,1],[14,0,"display-flex truncate align-items-center mr1"],[12],[1,"\\n                "],[8,[32,5],[[24,0,"profile-card-one-to-one__profile-link inline-block v-align-middle truncate"]],[["@href"],[[30,4,["recipientProfileUrl"]]]],[["default"],[[[[1,"\\n                  "],[10,1],[14,0,"truncate"],[12],[1,"\\n                    "],[1,[30,4,["participantName"]]],[1,"\\n                  "],[13],[1,"\\n                  "],[8,[32,6],null,[["@memberBadgeType","@classNames"],[[30,4,["recipientProfile","memberBadgeType"]],"ml1"]],null],[1,"\\n                "]],[]]]]],[1,"\\n              "],[13],[1,"\\n"]],[]],[[[1,"              "],[10,1],[14,0,"display-flex truncate align-items-center mr1"],[12],[1,"\\n"],[41,[30,0,["canShowSponsoredMemeberSenderProfileTooltip"]],[[[1,"                  "],[8,[32,7],[[24,0,"inline-block"]],[["@on","@placement"],["click","bottom"]],[["default"],[[[[1,"\\n                    "],[10,"button"],[14,0,"msg-s-message-group__name t-14 t-black t-bold"],[15,"aria-controls",[30,5,["ariaId"]]],[15,"aria-expanded",[30,5,["ariaExpanded"]]],[14,4,"button"],[12],[1,"\\n                      "],[10,1],[14,0,"inline-block v-align-middle truncate"],[12],[1,"\\n                        "],[1,[30,4,["participantName"]]],[1,"\\n                      "],[13],[1,"\\n                    "],[13],[1,"\\n                    "],[8,[30,5,["artdeco-hoverable-content"]],null,[["@theme","@contentClass"],["inverse","msg-s-message-group__preview-content"]],[["default"],[[[[1,"\\n                      "],[10,0],[14,0,"text-body-small-bold"],[12],[1,"\\n                        "],[1,[28,[32,3],["i18n_member_sender_header_tooltip","msg-conversation-ui/components/recipient-detail-one-to-one-presenter"],null]],[1,"\\n                      "],[13],[1,"\\n                      "],[10,"br"],[12],[13],[1,"\\n                      "],[10,0],[12],[1,"\\n                        "],[1,[28,[32,3],["i18n_member_sender_tooltip","msg-conversation-ui/components/recipient-detail-one-to-one-presenter"],null]],[1,"\\n                        "],[11,3],[16,6,[30,0,["sponsoredMemberSenderLearnMoreLink"]]],[24,"target","_blank"],[24,0,"link-without-visited-state"],[24,"rel","noopener noreferrer"],[4,[32,8],["click",[30,0,["fireSponosredMessagingInteractionEvent"]]],null],[12],[1,[28,[32,3],["i18n_tooltip_learn_more","msg-conversation-ui/components/recipient-detail-one-to-one-presenter"],null]],[1," "],[13],[1,"\\n                      "],[13],[1,"\\n                    "]],[]]]]],[1,"\\n                  "]],[5]]]]],[1,"\\n"]],[]],[[[1,"                  "],[10,1],[14,0,"inline-block v-align-middle truncate"],[12],[1,"\\n                    "],[1,[30,4,["participantName"]]],[1,"\\n                  "],[13],[1,"\\n"]],[]]],[1,"\\n                "],[8,[32,6],null,[["@memberBadgeType","@classNames"],[[30,4,["recipientProfile","memberBadgeType"]],"ml1"]],null],[1,"\\n\\n              "],[13],[1,"\\n"]],[]]],[41,[30,4,["pronounsObject","isResolved"]],[[[1,"              "],[8,[32,9],[[24,0,"t-14 t-black--light t-normal mr1"]],[["@pronounsObject"],[[30,4,["pronounsObject","value"]]]],null],[1,"\\n"]],[]],null],[41,[30,4,["recipientBadgeInfo"]],[[[1,"              "],[8,[30,3,["badge"]],[[24,0,"t-14 t-black--light t-normal"]],[["@degreeText","@degreeA11yText"],[[52,[30,4,["recipientBadgeInfo","textKey"]],[28,[32,3],[[30,4,["recipientBadgeInfo","textKey"]],"msg-conversation-ui/components/recipient-detail-one-to-one-presenter"],[["value"],[[30,4,["recipientBadgeInfo","value"]]]]]],[52,[30,4,["recipientBadgeInfo","a11yTextKey"]],[28,[32,3],[[30,4,["recipientBadgeInfo","a11yTextKey"]],"msg-conversation-ui/components/recipient-detail-one-to-one-presenter"],[["value"],[[30,4,["recipientBadgeInfo","value"]]]]]]]],null],[1,"\\n"]],[]],null],[1,"          "]],[]]]]],[1,"\\n\\n          "],[8,[30,3,["subtitle"]],null,null,[["default"],[[[[1,"\\n            "],[10,0],[15,"title",[30,4,["subtitle"]]],[12],[1,"\\n              "],[1,[30,4,["subtitle"]]],[1,"\\n            "],[13],[1,"\\n          "]],[]]]]],[1,"\\n\\n"],[41,[30,4,["verificationLabel"]],[[[1,"            "],[8,[32,7],null,[["@variant","@placement","@classNames"],["label","bottom","display-flex fit-content-width"]],[["default"],[[[[1,"\\n              "],[8,[32,10],null,[["@text","@type","@size","@classNames","@aria-describedby","@aria-label"],[[30,4,["verificationLabel"]],"secondary",1,"profile-card-one-to-one__pill",[30,6,["ariaId"]],[28,[32,3],["i18n_verified_recruiter","msg-conversation-ui/components/recipient-detail-one-to-one-presenter"],null]]],null],[1,"\\n              "],[8,[30,6,["artdeco-hoverable-content"]],null,[["@theme","@contentClass"],["inverse","profile-card-one-to-one__pill-hoverable"]],[["default"],[[[[1,"\\n                "],[1,[28,[32,11],[[30,4,["verificationExplanation"]]],null]],[1,"\\n              "]],[]]]]],[1,"\\n            "]],[6]]]]],[1,"\\n"]],[]],null],[1,"\\n"],[41,[30,7],[[[1,"            "],[8,[30,3,["metadata"]],null,[["@class"],["profile-card-one-to-one__context pt1"]],[["default"],[[[[1,"\\n"],[41,[30,0,["isContextTextModelV2"]],[[[1,"                "],[8,[32,12],null,[["@tvm"],[[30,7]]],null],[1,"\\n"]],[]],[[[1,"                "],[1,[28,[32,11],[[30,7]],null]],[1,"\\n"]],[]]],[1,"            "]],[]]]]],[1,"\\n"]],[]],null],[1,"\\n"],[41,[30,8],[[[1,"            "],[8,[30,3,["metadata"]],null,[["@class"],["pt1"]],[["default"],[[[[1,"\\n              "],[8,[32,12],null,[["@tvm"],[[30,8]]],null],[1,"\\n            "]],[]]]]],[1,"\\n"]],[]],null],[1,"        "]],[]]]]],[1,"\\n      "]],[3]]]]],[1,"\\n    "],[13],[1,"\\n  "]],["&attrs","@inlineLayout","elements","@viewData","trigger","trigger","@contextText","@invitationText"],false,["if"]]',moduleName:"msg-conversation-ui/components/recipient-detail-one-to-one-presenter.gjs",scope:()=>[c.default,d.default,m.default,g.default,u.default,p.default,v.default,y.default,P.on,f.default,_.default,h.default,b.default],isStrictMode:!0}),(x=(0,w.inject)("msg-spinmail-data@sponsored-action-tracking"),I=class extends s.default{constructor(){super(...arguments);(0,t.default)(this,"sponsoredActionTracking",O,this);(0,n.default)(this,"sponsoredMemberSenderLearnMoreLink",`${T.default.getDomainUrl()}/help/linkedin/answer/a426517`)}get isContextTextModelV2(){return!!this.args.contextText.attributesV2}get pageLogoPixelSize(){return this.args.inlineLayout?56:72}get profileNavigationEnabled(){const{viewData:e}=this.args
return e.isSponsoredConversation&&e.isRecipientOrganization?e.recipientProfileUrl:e.isSponsoredConversation?null:e.creatorProfileViewEnabled&&e.recipientProfileUrl}get canShowSponsoredMemeberSenderProfileTooltip(){return this.args.viewData.isConversationAdMemberSender&&this.args.viewData.isSponsoredConversation}fireSponosredMessagingInteractionEvent(){this.sponsoredActionTracking.fireSponosredMessagingInteractionEvent()}},O=(0,i.default)(I.prototype,"sponsoredActionTracking",[x],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),(0,i.default)(I.prototype,"fireSponosredMessagingInteractionEvent",[k.action],Object.getOwnPropertyDescriptor(I.prototype,"fireSponosredMessagingInteractionEvent"),I.prototype),I))}))
define("msg-conversation-ui/components/sender-side-warning-banner-presenter",["exports","@babel/runtime/helpers/esm/initializerDefineProperty","@babel/runtime/helpers/esm/defineProperty","@babel/runtime/helpers/esm/applyDecoratedDescriptor","@babel/runtime/helpers/esm/initializerWarningHelper","@ember/template-factory","@ember/helper","@ember/component","@glimmer/component","@ember/service","text-view-model/components/text-view-model-v2","image-view-model/components/image-view-model","artdeco-button/components/artdeco-button","ember-cli-pemberly-i18n/helpers/t","@ember/object","@glimmer/tracking","@ember/modifier"],(function(e,t,n,i,o,r,a,l,s,c,u,d,m,p,f,g,b){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var h,v,y,_
e.default=(0,l.setComponentTemplate)((0,r.createTemplateFactory)({id:"3Ks0Wmsb",block:'[[[1,"\\n"],[41,[30,0,["shouldShowBanner"]],[[[1,"      "],[10,0],[14,0,"msg-sender-side-warning-banner"],[12],[1,"\\n"],[41,[30,1,["icon"]],[[[1,"          "],[8,[32,0],[[24,0,"mr2"]],[["@images","@entitySize"],[[30,1,["icon"]],1]],null],[1,"\\n"]],[]],null],[1,"        "],[10,0],[14,0,"flex-column mr1"],[12],[1,"\\n"],[1,"          "],[10,2],[14,0,"text-body-xsmall-bold mb1"],[12],[8,[32,1],null,[["@tvm"],[[30,1,["title"]]]],null],[13],[1,"\\n"],[41,[30,1,["subtitle"]],[[[1,"            "],[10,2],[14,0,"text-body-xsmall"],[12],[8,[32,1],null,[["@tvm"],[[30,1,["subtitle"]]]],null],[13],[1,"\\n"]],[]],null],[1,"        "],[13],[1,"\\n"],[41,[30,1,["dismissable"]],[[[1,"          "],[8,[32,2],[[16,"aria-label",[28,[32,3],["i18n_a11y_dismiss_banner","msg-conversation-ui/components/sender-side-warning-banner-presenter"],null]],[4,[32,4],["click",[30,0,["dismissBanner"]]],null]],[["@class","@color","@icon","@type","@circle","@size"],["msg-sender-side-warning-banner__dismiss-button ph4","muted","close","tertiary","true",1]],null],[1,"\\n"]],[]],null],[1,"      "],[13],[1,"\\n"]],[]],null],[1,"  "]],["@bannerData"],false,["if"]]',moduleName:"msg-conversation-ui/components/sender-side-warning-banner-presenter.gjs",scope:()=>[d.default,u.default,m.default,p.default,b.on],isStrictMode:!0}),(h=(0,c.inject)("lego@tracking"),v=class extends s.default{get shouldShowBanner(){return!!this.args.bannerData&&!this.isDismissed}get legoTrackingId(){var e
return null===(e=this.args.bannerData)||void 0===e?void 0:e.legoTrackingId}constructor(){super(...arguments);(0,t.default)(this,"legoTracking",y,this);(0,t.default)(this,"isDismissed",_,this)
this.legoTrackingId&&this.legoTracking.sendLegoImpression(this.legoTrackingId,this.legoTracking.LEGO_IMPRESSION_VISIBILITY_SHOW)}dismissBanner(){this.legoTrackingId&&this.legoTracking.sendLegoAction(this.legoTrackingId,this.legoTracking.LEGO_ACTION_DISMISS,1)
this.isDismissed=!0}},y=(0,i.default)(v.prototype,"legoTracking",[h],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),_=(0,i.default)(v.prototype,"isDismissed",[g.tracked],{configurable:!0,enumerable:!0,writable:!0,initializer:function(){return!1}}),(0,i.default)(v.prototype,"dismissBanner",[f.action],Object.getOwnPropertyDescriptor(v.prototype,"dismissBanner"),v.prototype),v))}))
define("msg-conversation-ui/components/standard-footer-presenter",["exports","@babel/runtime/helpers/esm/initializerDefineProperty","@babel/runtime/helpers/esm/defineProperty","@babel/runtime/helpers/esm/applyDecoratedDescriptor","@babel/runtime/helpers/esm/initializerWarningHelper","@ember/template-factory","@ember/helper","@ember/component","@glimmer/component","text-view-model/components/text-view-model-v2","image-view-model/components/image-view-model","@ember/object","ember-cli-pemberly-i18n/helpers/t","@ember/modifier","@glimmer/tracking","ember-cli-pemberly-tracking/modifiers/track-render","lego/utils/constants","artdeco-button/components/artdeco-button","@ember/service"],(function(e,t,n,i,o,r,a,l,s,c,u,d,m,p,f,g,b,h,v){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var y,_,w,k,P,T
e.default=(0,l.setComponentTemplate)((0,r.createTemplateFactory)({id:"AZA1YDtl",block:'[[[1,"\\n"],[41,[30,0,["shouldRender"]],[[[1,"      "],[11,0],[24,0,"msg-s-conversation-standard-footer"],[4,[32,0],null,[["onRender","routeName","currentRoute"],[[30,0,["onLegoImpression"]],[28,[32,1],[[53,"outletState"],"render.name"],null],[28,[32,1],[[53,"outletState"],"render"],null]]]],[12],[1,"\\n        "],[10,2],[14,0,"msg-s-conversation-standard-footer__text"],[12],[1,"\\n"],[41,[30,1,["icon"]],[[[1,"            "],[8,[32,2],[[24,0,"inline-block v-align-middle"]],[["@images"],[[30,1,["icon"]]]],null],[1,"\\n"]],[]],null],[1,"\\n          "],[8,[32,3],null,[["@tvm"],[[30,1,["title"]]]],null],[1,"\\n\\n"],[41,[30,1,["subtitle"]],[[[1,"            "],[10,"br"],[14,0,"msg-s-conversation-standard-footer__subtitle-br"],[12],[13],[1,"\\n            "],[8,[32,3],null,[["@tvm"],[[30,1,["subtitle"]]]],null],[1,"\\n"]],[]],null],[1,"        "],[13],[1,"\\n\\n"],[41,[30,1,["dismissable"]],[[[1,"          "],[8,[32,4],[[24,0,""],[4,[32,6],["click",[30,0,["dismissFooter"]]],null]],[["@text","@type","@color","@size","@circle","@icon"],[[28,[32,5],["i18n_dismiss","msg-conversation-ui/components/standard-footer-presenter"],null],"tertiary","muted",1,true,"close"]],null],[1,"\\n"]],[]],null],[1,"      "],[13],[1,"\\n"]],[]],null],[1,"  "]],["@composeViewFooter"],false,["if","-get-dynamic-var"]]',moduleName:"msg-conversation-ui/components/standard-footer-presenter.gjs",scope:()=>[g.default,a.get,u.default,c.default,h.default,m.default,p.on],isStrictMode:!0}),(y=(0,v.inject)("lego@tracking"),_=(0,v.inject)("lix"),w=class extends s.default{constructor(){super(...arguments);(0,t.default)(this,"legoTracking",k,this);(0,t.default)(this,"lix",P,this);(0,t.default)(this,"showFooter",T,this)}get contentTrackingId(){return this.args.composeViewFooter.trackingId}get isActiveStatusBannerLixEnabled(){return this.lix.getTreatmentIsEnabled("voyager.web.messaging-active-status-banner")}get shouldRender(){return this.showFooter&&this.isActiveStatusBannerLixEnabled}onLegoImpression(){this.args.composeViewFooter.tundraTrackingId&&this.legoTracking.sendLegoImpression(this.args.composeViewFooter.tundraTrackingId,b.LEGO_IMPRESSION_VISIBILITY_SHOW)
return[]}dismissFooter(){this.showFooter=!1
this.args.composeViewFooter.tundraTrackingId&&this.legoTracking.sendLegoAction(this.args.composeViewFooter.tundraTrackingId,this.legoTracking.LEGO_ACTION_DISMISS)}},k=(0,i.default)(w.prototype,"legoTracking",[y],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),P=(0,i.default)(w.prototype,"lix",[_],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),T=(0,i.default)(w.prototype,"showFooter",[f.tracked],{configurable:!0,enumerable:!0,writable:!0,initializer:function(){return!0}}),(0,i.default)(w.prototype,"onLegoImpression",[d.action],Object.getOwnPropertyDescriptor(w.prototype,"onLegoImpression"),w.prototype),(0,i.default)(w.prototype,"dismissFooter",[d.action],Object.getOwnPropertyDescriptor(w.prototype,"dismissFooter"),w.prototype),w))}))
define("msg-conversation-ui/components/thread-bottom-card-feature",["exports","@ember/template-factory","@ember/component","@glimmer/component","msg-conversation-ui/components/profile-verification-footer-presenter","msg-conversation-ui/components/premium/premium-footer-presenter","msg-conversation-ui/components/profile-social-nudge-verification-footer-presenter","msg-conversation-ui/components/standard-footer-presenter"],(function(e,t,n,i,o,r,a,l){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class s extends i.default{get composeViewFooter(){var e,t
return null===(e=this.args.composeViewContext)||void 0===e||null===(t=e.value)||void 0===t?void 0:t.footer}get componentName(){var e
switch(null===(e=this.composeViewFooter)||void 0===e?void 0:e.type){case"PROFILE_VERIFICATION_FOOTER":return o.default
case"PREMIUM_INMAIL_FOLLOW_UP_FOOTER":return r.default
case"PROFILE_SOCIAL_NUDGE_VERIFICATION_FOOTER":return a.default
case"STANDARD_FOOTER":return l.default
default:return null}}}e.default=s;(0,n.setComponentTemplate)((0,t.createTemplateFactory)({id:"9omlh7qa",block:'[[[1,"\\n    "],[10,0],[14,0,"align-items-flex-end display-flex artdeco-divider"],[12],[1,"\\n"],[41,[30,0,["componentName"]],[[[44,[[50,[30,0,["componentName"]],0,null,null]],[[[1,"          "],[8,[30,1],null,[["@composeViewFooter","@conversation"],[[30,0,["composeViewFooter"]],[30,2]]],null],[1,"\\n"]],[1]]]],[]],null],[1,"    "],[13],[1,"\\n  "]],["Footer","@conversation"],false,["if","let","component"]]',moduleName:"msg-conversation-ui/components/thread-bottom-card-feature.gjs",isStrictMode:!0}),s)}))
define("msg-conversation-ui/components/thread-top-card-feature",["exports","@babel/runtime/helpers/esm/initializerDefineProperty","@babel/runtime/helpers/esm/defineProperty","@babel/runtime/helpers/esm/applyDecoratedDescriptor","@babel/runtime/helpers/esm/initializerWarningHelper","@ember/template-factory","@ember/component","msg-conversation-ui/viewdata/sdk-thread-top-card-viewdata","@glimmer/component","@ember/service","msg-conversation-ui/components/conversation-rename-presenter","msg-conversation-ui/components/premium-custom-cta-presenter","@ember/helper","msg-conversation-ui/components/sender-side-warning-banner-presenter","msg-conversation-ui/components/connection-invitation-presenter","msg-shared-modals/components/gdpr-notice","msg-conversation-ui/components/recipient-detail-one-to-one-presenter"],(function(e,t,n,i,o,r,a,l,s,c,u,d,m,p,f,g,b){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var h,v,y,_,w,k,P,T,x,I,O,D,M,C,S,j,N
e.default=(0,a.setComponentTemplate)((0,r.createTemplateFactory)({id:"plovJnlO",block:'[[[1,"\\n    "],[10,0],[14,0,"msg-thread-container msg-thread__thread-actions-tray"],[12],[1,"\\n"],[41,[30,1],[[[1,"        "],[8,[32,0],null,[["@actionTrackingPrefix","@viewData","@hideRenameConversationForm","@pageKey"],[[30,2],[30,0,["viewData","conversationRenameViewData"]],[28,[32,1],[[30,3],false],null],[30,4]]],null],[1,"\\n"]],[]],null],[41,[30,5,["isResolved"]],[[[41,[30,0,["showSenderSideWarningBanner"]],[[[1,"          "],[8,[32,2],null,[["@bannerData"],[[30,0,["composeViewHeader"]]]],null],[1,"\\n\\n"]],[]],[[[41,[30,0,["showPremiumCustomCta"]],[[[1,"          "],[8,[32,3],null,[["@composeViewHeader"],[[30,0,["composeViewHeader"]]]],null],[1,"\\n\\n"]],[]],[[[41,[30,0,["showConnectionInvitationBanner"]],[[[1,"          "],[8,[32,4],null,[["@viewData"],[[30,0,["viewData","connectionInvitationViewData"]]]],null],[1,"\\n        "]],[]],null]],[]]]],[]]]],[]],null],[1,"    "],[13],[1,"\\n\\n"],[41,[30,0,["showGdpr"]],[[[1,"      "],[8,[32,5],null,[["@noticeTypes"],[[30,6]]],null],[1,"\\n"]],[]],null],[1,"\\n"],[41,[30,7],[[[1,"      "],[8,[32,6],[[24,0,"ph3 pv2"]],[["@inlineLayout","@contextText","@invitationText","@viewData"],[[30,8],[30,9],[30,0,["invitationText"]],[30,0,["viewData","recipientDetailOneToOneViewData"]]]],null],[1,"\\n"]],[]],null],[1,"  "]],["@showRenameConversationForm","@actionTrackingPrefix","@toggleShowRenameConversation","@renamePageKey","@composeViewContext","@noticeTypes","@showRecipientDetailOneToOne","@isOriginalSize","@contextText"],false,["if"]]',moduleName:"msg-conversation-ui/components/thread-top-card-feature.gjs",scope:()=>[u.default,m.fn,p.default,d.default,f.default,g.default,b.default],isStrictMode:!0}),(h=(0,c.inject)("authentication@authenticated-user"),v=(0,c.inject)("invitation-platform@invitation-platform"),y=(0,c.inject)("profile-services@identity-store"),_=(0,c.inject)("formatter"),w=(0,c.inject)("lix"),k=(0,c.inject)("msg-data@data-manager"),P=(0,c.inject)("router"),T=(0,c.inject)("global-services@store-shim"),x=class extends s.default{constructor(){super(...arguments);(0,t.default)(this,"authenticatedUser",I,this);(0,t.default)(this,"invitationPlatform",O,this);(0,t.default)(this,"identityStore",D,this);(0,t.default)(this,"formatter",M,this);(0,t.default)(this,"lix",C,this);(0,t.default)(this,"msgDataManager",S,this);(0,t.default)(this,"router",j,this);(0,t.default)(this,"storeShim",N,this)}get viewData(){const{authenticatedUser:e,formatter:t,identityStore:n,invitationPlatform:i,msgDataManager:o,router:r,storeShim:a,lix:s}=this
return new l.default({conversation:this.args.conversation,profile:this.args.recipientProfile,invitationPlatform:i,identityStore:n,formatter:t,msgDataManager:o,authenticatedUser:e,router:r,store:a,lix:s,isCustomInviteReply:!!this.invitationText})}get showConnectionInvitationBanner(){const{latestMessageIsInMail:e,isPremiumInMailOrReply:t,isInMailOrInMailReply:n,isPendingOrDeclinedMessageRequest:i,participantIsBlocked:o,participantIsConnected:r,latestEvent:a,isGroupChat:l}=this.viewData,s=this.invitationText&&this.viewData.connectionInvitationViewData.pendingInvitation
if(!a&&!s)return!1
return!(n&&(e||!t)||o||r||i||l)}get showGdpr(){return this.viewData.latestMessageIsInMail}get composeViewHeader(){var e,t
return null===(e=this.args.composeViewContext)||void 0===e||null===(t=e.value)||void 0===t?void 0:t.header}get showPremiumCustomCta(){var e
return"PREMIUM_CUSTOM_CTA"===(null===(e=this.composeViewHeader)||void 0===e?void 0:e.type)}get invitationText(){var e,t
return null===(e=this.args.composeViewContext)||void 0===e||null===(t=e.value)||void 0===t?void 0:t.invitationText}get showSenderSideWarningBanner(){var e,t
return!(null!==(e=this.args.conversation)&&void 0!==e&&e.entityUrn)&&"SENDER_SIDE_WARNING"===(null===(t=this.composeViewHeader)||void 0===t?void 0:t.type)}},I=(0,i.default)(x.prototype,"authenticatedUser",[h],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),O=(0,i.default)(x.prototype,"invitationPlatform",[v],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),D=(0,i.default)(x.prototype,"identityStore",[y],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),M=(0,i.default)(x.prototype,"formatter",[_],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),C=(0,i.default)(x.prototype,"lix",[w],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),S=(0,i.default)(x.prototype,"msgDataManager",[k],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),j=(0,i.default)(x.prototype,"router",[P],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),N=(0,i.default)(x.prototype,"storeShim",[T],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),x))}))
define("msg-conversation-ui/template-registry",[],(function(){}))
define("msg-conversation-ui/viewdata/compose-recipient-detail-one-to-one-viewdata",["exports","@babel/runtime/helpers/esm/applyDecoratedDescriptor","presence/viewdata/host-entity-with-presence-viewdata","ember-async-data","msg-data/viewdata","data-layer/utils/profile/get-profile","tracked-toolbox"],(function(e,t,n,i,o,r,a){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var l
e.default=(l=class extends o.default{get profile(){return this.props.profile}get recipientProfileUrl(){const e=this.props.profile.publicIdentifier
if(e)return this.props.router.urlFor("profile.common.profile",{vanityName:e})}get participantName(){return this.props.participantName}get subtitle(){const{profile:e}=this.props
return e.headline??e.occupation}get creatorProfileViewEnabled(){return this.recipientProfileUrl}get recipientBadgeInfo(){return this.recipientDistance.isResolved&&this.recipientDistance.value?{textKey:"i18n_distance",a11yTextKey:"i18n_distance_a11y",value:this.recipientDistance.value}:null}get recipientDistance(){return this.props.isInvitationAccepted()?new i.TrackedAsyncData("DISTANCE_1"):new i.TrackedAsyncData(this.props.msgDataManager.fetchConnectionStatus(this.props.profile.entityUrn.replace("fs_miniProfile","fsd_profile")).then((e=>e.memberDistance)))}get pronounsObject(){return new i.TrackedAsyncData((0,r.getProfileById)(this.props.store,this.props.profileId,"com.linkedin.voyager.dash.deco.identity.profile.FullProfile").then((e=>e.pronounUnion)))}get entityWithPresenceViewData(){return new n.default({profile:this.props.profile,altText:this.participantName})}},(0,t.default)(l.prototype,"recipientBadgeInfo",[a.cached],Object.getOwnPropertyDescriptor(l.prototype,"recipientBadgeInfo"),l.prototype),(0,t.default)(l.prototype,"recipientDistance",[a.cached],Object.getOwnPropertyDescriptor(l.prototype,"recipientDistance"),l.prototype),(0,t.default)(l.prototype,"pronounsObject",[a.cached],Object.getOwnPropertyDescriptor(l.prototype,"pronounsObject"),l.prototype),l)}))
define("msg-conversation-ui/viewdata/sdk-connection-invitation-viewdata",["exports","msg-data/viewdata","msg-data/utils/sdk-view-data-helpers","urn-utils"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class o extends t.default{get conversationEntityUrn(){return this.props.conversation.entityUrn}get recipientProfileId(){const e=(0,n.getNonSelfParticipants)(this.props.conversation.decoratedParticipants,this.props.authenticatedUser.miniProfile)
return e&&e.length?(0,i.extractEntityInfoFromUrn)(e[0].hostIdentityUrn).id:null}get recipientProfileUrn(){var e
const t=(0,n.getNonSelfParticipants)(this.props.conversation.decoratedParticipants,this.props.authenticatedUser.miniProfile)
return t?null===(e=t[0])||void 0===e?void 0:e.hostIdentityUrn:null}get pendingInvitation(){var e
return(null===(e=this.props.msgDataManager.connectionStatusMap.get(this.recipientProfileUrn))||void 0===e?void 0:e.pendingInvitation)??null}get participantName(){var e
return null===(e=(0,n.getNonSelfParticipants)(this.props.conversation.decoratedParticipants,this.props.authenticatedUser.miniProfile))||void 0===e?void 0:e[0]}get hasPendingInvitationReceived(){const e=this.props.msgDataManager.connectionStatusMap.get(this.recipientProfileUrn)
return(null==e?void 0:e.pendingInvitation)&&"RECEIVED"===(null==e?void 0:e.invitationType)}get hasPendingInvitationSent(){const e=this.props.msgDataManager.connectionStatusMap.get(this.recipientProfileUrn)
return(null==e?void 0:e.pendingInvitation)&&"SENT"===(null==e?void 0:e.invitationType)||this.props.invitationPlatform.hasPendingInvitation(this.recipientProfileId)}}e.default=o}))
define("msg-conversation-ui/viewdata/sdk-conversation-rename-viewdata",["exports","msg-data/viewdata"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class n extends t.default{get conversationEntityUrn(){return this.props.conversation.entityUrn}get conversationName(){return this.props.conversation.title}get disableRemovingName(){const{groupChat:e,participants:t}=this.props.conversation
return e&&t.length<=2}}e.default=n}))
define("msg-conversation-ui/viewdata/sdk-custom-invite-reply-connection-invitation-viewdata",["exports","msg-conversation-ui/viewdata/sdk-connection-invitation-viewdata","global-helpers/helpers/name","urn-utils"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class o extends t.default{get recipientProfileId(){return(0,i.extractEntityInfoFromUrn)(this.props.recipientProfileUrn).id}get recipientProfileUrn(){return this.props.recipientProfileUrn}get participantName(){return(0,n.getName)(this.props.profile)}}e.default=o}))
define("msg-conversation-ui/viewdata/sdk-recipient-detail-group-viewdata",["exports","pronouns/utils/helpers","presence/viewdata/sdk-entity-with-presence-viewdata","global-helpers/helpers/name","msg-data/viewdata","msg-shared-modals/viewdata/sdk-conversation-modals-viewdata","msg-data/utils/sdk-view-data-helpers"],(function(e,t,n,i,o,r,a){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class l extends o.default{get allowAddParticipant(){return!!this.isViewerCurrentParticipant&&(0,a.isConversationFeatureSupported)(this.props.conversation,"ADD_PARTICIPANT")}get allowRenameConversation(){return(0,a.isConversationFeatureSupported)(this.props.conversation,"RENAMED_CONVERSATION")}get recipientProfiles(){return this.participants.map((e=>({participantProfileUrl:e.profile.url??"",pronoun:(0,t.formatPronouns)(e,this.props.i18n),name:(0,i.getName)(e),entityWithPresenceViewData:new n.default({participant:e,altText:this.props.formatter.formatName(e,"full")}),showPremiumInBug:e.showPremiumInBug,showVerificationBadge:e.showVerificationBadge,memberBadgeType:e.memberBadgeType})))}get participants(){var e
return null===(e=this.props.conversation)||void 0===e?void 0:e.decoratedParticipants}get headlineText(){return this.props.conversation.headlineText}get conversationDescription(){return this.props.conversation.descriptionText}get headlineImage(){return null}get title(){return this.props.conversation.title}get conversationModalsViewData(){var e
const{conversation:t,authenticatedUser:n,formatter:i,presenceAPI:o}=this.props
return new r.default({conversation:t,participants:this.participants,authenticatedUserProfile:null===(e=n.miniProfile)||void 0===e?void 0:e.content,formatter:i,presenceAPI:o})}get isViewerCurrentParticipant(){var e,t
return this.props.conversation&&(null===(e=this.props.conversation.participants)||void 0===e?void 0:e.includes(null===(t=this.props.authenticatedUser.miniProfile)||void 0===t?void 0:t.dashEntityUrn))}}e.default=l}))
define("msg-conversation-ui/viewdata/sdk-recipient-detail-one-to-one-viewdata",["exports","@babel/runtime/helpers/esm/applyDecoratedDescriptor","presence/viewdata/sdk-entity-with-presence-viewdata","ember-async-data","msg-data/viewdata","msg-data/utils/sdk-view-data-helpers","tracked-toolbox"],(function(e,t,n,i,o,r,a){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var l
e.default=(l=class extends o.default{get isRecipientOrganization(){return this.props.profile.kind===r.PARTICIPANT_TYPES.ORGANIZATION}get isSponsoredConversation(){return(0,r.isSponsoredConversation)(this.props.conversation)}get recipientBadgeInfo(){return this.isRecipientOrganization&&this.props.profile.following?{textKey:"i18n_following",a11yTextKey:"i18n_following_a11y",value:this.participantName}:this.recipientDistance.isResolved&&this.recipientDistance.value&&"DISTANCE_UNKNOWN"!==this.recipientDistance.value?{textKey:"i18n_distance",a11yTextKey:"i18n_distance_a11y",value:this.recipientDistance.value}:null}get subtitle(){var e
if(this.isRecipientOrganization&&null!==(e=this.props.profile.industryName)&&void 0!==e&&e.text){var t
return null===(t=this.props.profile.industryName)||void 0===t?void 0:t.text}return this.props.profile.headline}get recipientProfileUrl(){return this.isRecipientOrganization?this.props.profile.pageUrl:this.props.profile.profile.url}get recipientProfile(){return this.props.profile}get participantName(){return this.props.participantName}get recipientDistance(){if(this.props.isInvitationAccepted())return new i.TrackedAsyncData("DISTANCE_1")
const e=this.props.msgDataManager.connectionStatusMap.get(this.props.profileId),t=e?e.memberDistance:"DISTANCE_UNKNOWN"
return new i.TrackedAsyncData(t)}get pronounsObject(){return new i.TrackedAsyncData(this.props.profile.pronoun)}get creatorProfileViewEnabled(){const{conversation:e}=this.props
return(0,r.isConversationFeatureSupported)(e,"VIEW_CREATOR_PROFILE")&&null!==this.recipientProfileUrl}get entityWithPresenceViewData(){return new n.default({participant:this.props.profile,altText:this.participantName})}get pageLogo(){return this.props.profile.logo}get verificationLabel(){var e
return null===(e=this.props.conversation.conversationVerificationLabel)||void 0===e?void 0:e.text}get verificationExplanation(){return this.props.conversation.conversationVerificationExplanation}get isConversationAdMemberSender(){return this.props.profile.kind===r.PARTICIPANT_TYPES.MEMBER}},(0,t.default)(l.prototype,"recipientDistance",[a.cached],Object.getOwnPropertyDescriptor(l.prototype,"recipientDistance"),l.prototype),(0,t.default)(l.prototype,"pronounsObject",[a.cached],Object.getOwnPropertyDescriptor(l.prototype,"pronounsObject"),l.prototype),l)}))
define("msg-conversation-ui/viewdata/sdk-thread-top-card-viewdata",["exports","global-utils/utils/profile-id-parser","global-helpers/helpers/name","msg-conversation-ui/viewdata/sdk-conversation-rename-viewdata","msg-data/viewdata","msg-conversation-ui/viewdata/sdk-connection-invitation-viewdata","msg-conversation-ui/viewdata/sdk-custom-invite-reply-connection-invitation-viewdata","msg-conversation-ui/viewdata/compose-recipient-detail-one-to-one-viewdata","msg-data/utils/sdk-view-data-helpers","msg-shared/helpers/is-message-request-conversation","urn-utils"],(function(e,t,n,i,o,r,a,l,s,c,u){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class d extends o.default{get isInMailOrInMailReply(){return(0,s.isInMailConversation)(this.props.conversation)}get latestMessageIsInMail(){var e,t
const n=null===(e=this.props.conversation)||void 0===e||null===(t=e.messages)||void 0===t?void 0:t.last()
return(0,s.messageHasInMailHostUrnData)(n)}get isPremiumInMailOrReply(){var e,t
const n=null===(e=this.props.conversation)||void 0===e||null===(t=e.messages)||void 0===t?void 0:t.first()
return(0,s.messageHasInMailProductType)(n,"PREMIUM_INMAIL")}get participantIsBlocked(){}get participantIsConnected(){const e=this.recipientProfileUrn?(0,u.extractEntityInfoFromUrn)(this.recipientProfileUrn).id:null,t=this.props.msgDataManager.connectionStatusMap.get(this.recipientProfileUrn)
return!t||(t.isConnected||this.props.invitationPlatform.isInvitationAccepted(e))}get isGroupChat(){var e
return null===(e=this.props.conversation)||void 0===e?void 0:e.groupChat}get recipientProfileUrn(){var e,t
const n=(null===(e=this.props.conversation)||void 0===e?void 0:e.participants)||(null===(t=this.props.conversation)||void 0===t?void 0:t.recipients)||[],[i]=n.filter((e=>e!==this.props.authenticatedUser.miniProfile.dashEntityUrn))??[]
return i}get latestEvent(){const{conversation:e,msgDataManager:t}=this.props
return e&&(0,s.getLatestMessage)(e,t)}get isPendingOrDeclinedMessageRequest(){const{conversation:e}=this.props
return(0,c.isMessageRequestConversation)(e)}get conversationRenameViewData(){const{conversation:e}=this.props
return new i.default({conversation:e})}get connectionInvitationViewData(){const{conversation:e,invitationPlatform:t,authenticatedUser:n,msgDataManager:i,isCustomInviteReply:o,profile:l}=this.props
return o?new a.default({conversation:e,invitationPlatform:t,authenticatedUser:n,msgDataManager:i,profile:l,recipientProfileUrn:this.recipientProfileUrn}):new r.default({conversation:e,invitationPlatform:t,authenticatedUser:n,msgDataManager:i})}get recipientDetailOneToOneViewData(){const{profile:e,formatter:i,router:o,identityStore:r,store:a,lix:s,msgDataManager:c}=this.props,u=(0,t.getProfileMemberId)(e)
return new l.default({profile:e,profileId:u,participantName:i.formatName((0,n.getName)(e),"full"),router:o,identityStore:r,store:a,lix:s,msgDataManager:c,isInvitationAccepted:()=>this.props.invitationPlatform.isInvitationAccepted(u)})}}e.default=d}))
define("msg-conversation-ui/viewdata/sdk-typing-indicators-viewdata",["exports","msg-data/viewdata"],(function(e,t){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class n extends t.default{get typingParticipants(){return this.props.typingParticipants.map((e=>({isTyping:!0,image:e.profile.picture,fullName:this.props.formatter.formatName(e,"full")})))}}e.default=n}))
define("msg-mentions/components/mention-all-picker-option-presenter",["exports","@ember/template-factory","@ember/helper","@ember/component/template-only","@ember/component","@ember/modifier","ember-cli-pemberly-i18n/helpers/t"],(function(e,t,n,i,o,r,a){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
const l=(0,o.setComponentTemplate)((0,t.createTemplateFactory)({id:"wZu8n8Cy",block:'[[[1,"\\n"],[1,"  "],[11,"li"],[24,"tabindex","0"],[24,0,"msg-form__mention-option"],[24,"data-mentions-picker-option",""],[4,[32,0],["click",[30,1]],null],[4,[32,0],["keydown",[30,2]],null],[12],[1,"\\n"],[1,"    "],[10,1],[14,0,"EntityPhoto-circle-2 ghost-group"],[12],[1,"\\n    "],[13],[1,"\\n    "],[10,0],[14,0,"display-flex flex-column pl2 truncate"],[12],[1,"\\n      "],[10,1],[14,0,"t-14 t-black t-bold truncate"],[12],[1,"\\n        "],[1,[28,[32,1],["i18n_mention_all","msg-mentions/components/mention-all-picker-option-presenter"],null]],[1,"\\n      "],[13],[1,"\\n      "],[10,1],[14,0,"t-12 t-black--light t-normal truncate"],[12],[1,"\\n        "],[1,[28,[32,1],["i18n_notify_entire_group","msg-mentions/components/mention-all-picker-option-presenter"],null]],[1,"\\n      "],[13],[1,"\\n    "],[13],[1,"\\n  "],[13],[1,"\\n"]],["@onClick","@onKeyDown"],false,[]]',moduleName:"msg-mentions/components/mention-all-picker-option-presenter.gjs",scope:()=>[r.on,a.default],isStrictMode:!0}),(0,i.default)("mention-all-picker-option-presenter","MentionAllPickerOptionPresenter"))
e.default=l}))
define("msg-mentions/components/mention-to-invite-toast-presenter",["exports","@babel/runtime/helpers/esm/initializerDefineProperty","@babel/runtime/helpers/esm/defineProperty","@babel/runtime/helpers/esm/applyDecoratedDescriptor","@babel/runtime/helpers/esm/initializerWarningHelper","@ember/template-factory","@ember/component","global-utils/utils/is-browser","@ember/debug","@ember/object/internals","global-helpers/helpers/name","@ember/object","@glimmer/tracking","@glimmer/component","@ember/service","artdeco-card/components/artdeco-card","ember-cli-pemberly-i18n/helpers/t","@ember/render-modifiers/modifiers/did-insert","hue-web-icons/components/icon","global-helpers/helpers/gte","@ember/helper","ember-cli-pemberly-tracking/modifiers/track-interaction","@ember/modifier","ember-set-helper/helpers/set","artdeco-modal/components/artdeco-confirmation-dialog"],(function(e,t,n,i,o,r,a,l,s,c,u,d,m,p,f,g,b,h,v,y,_,w,k,P,T){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
var x,I,O,D,M,C,S,j,N,E,A,L
e.default=(0,a.setComponentTemplate)((0,r.createTemplateFactory)({id:"AVoROCly",block:'[[[1,"\\n"],[1,"\\n"],[41,[30,1],[[[1,"      "],[8,[32,0],[[24,0,"msg-form__mention-to-invite-toast-card"],[16,1,[30,0,["mentionToInviteToastId"]]],[4,[32,2],[[30,0,["onInsert"]]],null]],[["@isDismissable","@onDismiss","@dismissText","@tabindex"],[true,[30,0,["closeToast"]],[28,[32,1],["a11y_dismiss_mention-to-invite-toast","msg-mentions/components/mention-to-invite-toast-presenter"],null],"0"]],[["default"],[[[[1,"\\n        "],[10,1],[14,0,"msg-form__mention-to-invite-toast-icon mr2"],[12],[1,"\\n          "],[8,[32,3],null,[["@type","@name","@size"],["system","signal-notice","medium"]],null],[1,"\\n        "],[13],[1,"\\n        "],[10,0],[14,0,"mr4 t-14"],[12],[1,"\\n          "],[10,1],[14,"tabindex","0"],[14,0,"msg-form__mention-to-invite-toast-card__text mr1"],[12],[1,"\\n"],[41,[28,[32,4],[2,[30,1,["length"]]],null],[[[1,"              "],[1,[28,[32,1],["i18n_up_to_2_participants_not_in_group_conversation","msg-mentions/components/mention-to-invite-toast-presenter"],[["names","count"],[[30,0,["membersToInviteNames"]],[30,1,["length"]]]]]],[1,"\\n"]],[]],[[[1,"              "],[1,[28,[32,1],["i18n_3_or_more_participants_not_in_group_conversation","msg-mentions/components/mention-to-invite-toast-presenter"],[["name1","name2","othersCount"],[[28,[32,5],[[30,0,["membersToInviteNames"]],"0"],null],[28,[32,5],[[30,0,["membersToInviteNames"]],"1"],null],[30,0,["othersCount"]]]]]],[1,"\\n"]],[]]],[1,"          "],[13],[1,"\\n          "],[11,3],[24,"tabindex","0"],[24,6,"#"],[16,"aria-label",[28,[32,1],["a11y_add_mentioned_members","msg-mentions/components/mention-to-invite-toast-presenter"],null]],[24,0,"msg-form__mention-to-invite-toast-link"],[4,[32,6],[[30,0,["addThemInteractionName"]]],null],[4,[32,7],["click",[28,[32,8],[[30,0],"showConfirmModal",true],null]],null],[12],[1,"\\n            "],[1,[28,[32,1],["i18n_add_them","msg-mentions/components/mention-to-invite-toast-presenter"],null]],[1,"\\n          "],[13],[1,"\\n        "],[13],[1,"\\n      "]],[]]]]],[1,"\\n"]],[]],null],[1,"\\n    "],[8,[32,9],null,[["@isOpen","@title","@content","@primaryActionText","@primaryActionTextA11y","@secondaryActionText","@secondaryActionTextA11y","@onPrimary","@onSecondary","@onEscape","@primaryControlName","@size"],[[30,0,["showConfirmModal"]],[52,[28,[32,4],[2,[30,1,["length"]]],null],[28,[32,1],["i18n_add_up_to_2_members_to_this_conversation_prompt","msg-mentions/components/mention-to-invite-toast-presenter"],[["names"],[[30,0,["membersToInviteNames"]]]]],[28,[32,1],["i18n_add_3_or_more_members_to_this_conversation_prompt","msg-mentions/components/mention-to-invite-toast-presenter"],[["name1","name2","othersCount"],[[28,[32,5],[[30,0,["membersToInviteNames"]],"0"],null],[28,[32,5],[[30,0,["membersToInviteNames"]],"1"],null],[30,0,["othersCount"]]]]]],[28,[32,1],["i18n_new_members_will_see_history","msg-mentions/components/mention-to-invite-toast-presenter"],null],[28,[32,1],["i18n_yes","msg-mentions/components/mention-to-invite-toast-presenter"],null],[28,[32,1],["a11y_confirm_add_mentioned_members","msg-mentions/components/mention-to-invite-toast-presenter"],null],[28,[32,1],["i18n_cancel","msg-mentions/components/mention-to-invite-toast-presenter"],null],[28,[32,1],["a11y_dismiss_add_mentioned_members","msg-mentions/components/mention-to-invite-toast-presenter"],null],[30,0,["addParticipants"]],[30,0,["closeModal"]],[30,0,["closeModal"]],[30,0,["addConfirmationInteractionName"]],"medium"]],null],[1,"\\n  "]],["@membersToInvite"],false,["if"]]',moduleName:"msg-mentions/components/mention-to-invite-toast-presenter.gjs",scope:()=>[g.default,b.default,h.default,v.default,y.default,_.get,w.default,k.on,P.default,T.default],isStrictMode:!0}),(x=(0,f.inject)("msg-data@data-manager"),I=(0,f.inject)("tracking"),O=(0,f.inject)("persistent-toast-manager@persistent-toast-manager"),D=(0,f.inject)("i18n"),M=(0,f.inject)("global-services@a11y-notification"),C=class extends p.default{constructor(){super(...arguments);(0,n.default)(this,"mentionToInviteToastId",`mention-to-invite-toast-${(0,c.guidFor)(this)}`);(0,t.default)(this,"msgDataManager",S,this);(0,t.default)(this,"tracking",j,this);(0,t.default)(this,"persistentToastManager",N,this);(0,t.default)(this,"i18n",E,this);(0,t.default)(this,"a11yNotification",A,this);(0,t.default)(this,"showConfirmModal",L,this)}get membersToInviteNames(){var e
return null===(e=this.args.membersToInvite)||void 0===e?void 0:e.map(u.getName)}get othersCount(){var e
return null!==(e=this.args.membersToInvite)&&void 0!==e&&e.length?this.args.membersToInvite.length-2:0}get actionTrackingPrefix(){return this.args.actionTrackingPrefix??""}get addThemInteractionName(){return this.actionTrackingPrefix.concat("at_mention_add_them")}get addConfirmationInteractionName(){return this.actionTrackingPrefix.concat("at_mention_confirmation_add")}onInsert(){if(l.default){const e=document.getElementById(this.mentionToInviteToastId).querySelector(".msg-form__mention-to-invite-toast-card__text")
if(e){e.focus()
const t=this.args.membersToInvite.length
t<=2?this.a11yNotify("i18n_up_to_2_participants_not_in_group_conversation",{names:this.membersToInviteNames,count:t}):this.a11yNotify("i18n_3_or_more_participants_not_in_group_conversation",{name1:this.membersToInviteNames[0],name2:this.membersToInviteNames[1],othersCount:this.othersCount})}}}addToast(){const e=this.i18n.lookupTranslation(this.constructor,"i18n_num_participants_added")([{count:this.addedParticipantsCount}])
this.persistentToastManager.success({message:e})}a11yNotify(e,t){const n=this.i18n.lookupTranslation(this.constructor,e)
this.a11yNotification.setTextInLiveRegion(n([t]))}addParticipants(){var e,t
const{conversationUrn:n}=this.args.viewData
this.addedParticipantsCount=this.args.membersToInvite.length
this.msgDataManager.addParticipants(this.args.membersToInvite.map((e=>e.entityUrn)),n).then((()=>{this.isDestroying||this.addToast()}))
this.showConfirmModal=!1
null===(e=(t=this.args).onToastDismiss)||void 0===e||e.call(t)}closeModal(){var e,t
this.tracking.fireInteractionEvent(`${this.actionTrackingPrefix}at_mention_confirmation_cancel`)
this.showConfirmModal=!1
null===(e=(t=this.args).onToastDismiss)||void 0===e||e.call(t)}closeToast(){var e,t
this.tracking.fireInteractionEvent(`${this.actionTrackingPrefix}at_mention_x_out`)
null===(e=(t=this.args).onToastDismiss)||void 0===e||e.call(t)}},S=(0,i.default)(C.prototype,"msgDataManager",[x],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),j=(0,i.default)(C.prototype,"tracking",[I],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),N=(0,i.default)(C.prototype,"persistentToastManager",[O],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),E=(0,i.default)(C.prototype,"i18n",[D],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),A=(0,i.default)(C.prototype,"a11yNotification",[M],{configurable:!0,enumerable:!0,writable:!0,initializer:null}),L=(0,i.default)(C.prototype,"showConfirmModal",[m.tracked],{configurable:!0,enumerable:!0,writable:!0,initializer:function(){return!1}}),(0,i.default)(C.prototype,"onInsert",[d.action],Object.getOwnPropertyDescriptor(C.prototype,"onInsert"),C.prototype),(0,i.default)(C.prototype,"addParticipants",[d.action],Object.getOwnPropertyDescriptor(C.prototype,"addParticipants"),C.prototype),(0,i.default)(C.prototype,"closeModal",[d.action],Object.getOwnPropertyDescriptor(C.prototype,"closeModal"),C.prototype),(0,i.default)(C.prototype,"closeToast",[d.action],Object.getOwnPropertyDescriptor(C.prototype,"closeToast"),C.prototype),C))}))
define("msg-mentions/components/mentions-picker-option-presenter",["exports","@ember/template-factory","@ember/helper","@ember/component/template-only","@ember/component","@ember/modifier","presence/components/entity-with-presence-presenter"],(function(e,t,n,i,o,r,a){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
const l=(0,o.setComponentTemplate)((0,t.createTemplateFactory)({id:"BOndtOCG",block:'[[[1,"\\n"],[1,"  "],[11,"li"],[24,"tabindex","0"],[24,"data-mentions-picker-option",""],[24,0,"msg-form__mention-option"],[4,[32,0],["click",[30,1]],null],[4,[32,0],["keydown",[30,2]],null],[12],[1,"\\n"],[1,"    "],[8,[32,1],[[24,0,"msg-form__mention-entity"]],[["@viewData","@size"],[[30,3,["entityWithPresenceViewData"]],2]],null],[1,"\\n    "],[10,0],[14,0,"display-flex flex-column pl2 truncate"],[12],[1,"\\n      "],[10,1],[14,0,"t-14 t-black t-bold truncate"],[12],[1,"\\n        "],[1,[30,3,["title"]]],[1,"\\n      "],[13],[1,"\\n      "],[10,1],[14,0,"t-12 t-black--light t-normal truncate"],[12],[1,"\\n        "],[1,[30,3,["subtitle"]]],[1,"\\n      "],[13],[1,"\\n    "],[13],[1,"\\n  "],[13],[1,"\\n"]],["@selectMention","@selectMentionWithKeyDown","@viewData"],false,[]]',moduleName:"msg-mentions/components/mentions-picker-option-presenter.gjs",scope:()=>[r.on,a.default],isStrictMode:!0}),(0,i.default)("mentions-picker-option-presenter","MentionsPickerOptionPresenter"))
e.default=l}))
define("msg-mentions/components/mentions-picker-presenter",["exports","@ember/template-factory","@ember/component/template-only","@ember/component","global-modifiers/modifiers/on-click-outside","@ember/modifier","msg-mentions/components/mention-all-picker-option-presenter","@ember/helper","msg-mentions/components/mentions-picker-option-presenter","ember-cli-pemberly-i18n/helpers/t"],(function(e,t,n,i,o,r,a,l,s,c){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
const u=(0,i.setComponentTemplate)((0,t.createTemplateFactory)({id:"VRK4QmAX",block:'[[[1,"\\n"],[1,"  "],[11,"ul"],[16,0,[29,["msg-form__mentions-picker\\n      ",[52,[51,[30,1]],"msg-form__mentions-picker--auto-selected"],"\\n      scrollable"]]],[24,"data-mentions-picker",""],[24,"role","listbox"],[16,5,[30,2]],[4,[32,0],[[30,3]],null],[4,[32,1],["keydown",[30,4]],null],[12],[1,"\\n"],[41,[30,5],[[[1,"      "],[8,[32,2],null,[["@onClick","@onKeyDown"],[[28,[32,3],[[30,6],[30,7]],null],[28,[32,3],[[30,8],[30,7]],null]]],null],[1,"\\n"]],[]],null],[42,[28,[31,3],[[28,[31,3],[[30,9,["conversationParticipantMentionOptions"]]],null]],null],null,[[[1,"      "],[8,[32,4],null,[["@viewData","@selectMention","@selectMentionWithKeyDown"],[[30,10],[28,[32,3],[[30,6],[30,10,["editorAttribute"]]],null],[28,[32,3],[[30,8],[30,10,["editorAttribute"]]],null]]],null],[1,"\\n"]],[10]],null],[41,[30,9,["connectionMentionOptions","length"]],[[[1,"      "],[10,"li"],[14,0,"msg-form__mentions-picker-connections-title t-12 t-black--light t-bold ph2 pt2 pb1"],[12],[1,"\\n        "],[1,[28,[32,5],["i18n_connections_header","msg-mentions/components/mentions-picker-presenter"],null]],[1,"\\n      "],[13],[1,"\\n"]],[]],null],[42,[28,[31,3],[[28,[31,3],[[30,9,["connectionMentionOptions"]]],null]],null],null,[[[1,"      "],[8,[32,4],null,[["@viewData","@selectMention","@selectMentionWithKeyDown"],[[30,11],[28,[32,3],[[30,6],[30,11,["editorAttribute"]]],null],[28,[32,3],[[30,8],[30,11,["editorAttribute"]]],null]]],null],[1,"\\n"]],[11]],null],[1,"  "],[13],[1,"\\n"]],["@isTabbingThroughMentions","@mentionsTopPosition","@closeMentions","@onKeyDown","@showMentionAllOption","@selectMention","@mentionAll","@selectMentionWithKeyDown","@viewData","optionViewData","optionViewData"],false,["unless","if","each","-track-array"]]',moduleName:"msg-mentions/components/mentions-picker-presenter.gjs",scope:()=>[o.default,r.on,a.default,l.fn,s.default,c.default],isStrictMode:!0}),(0,n.default)("mentions-picker-presenter","MentionsPickerPresenter"))
e.default=u}))
define("msg-mentions/template-registry",[],(function(){}))
define("msg-mentions/viewdata/connection-mentions-picker-option-viewdata",["exports","global-helpers/helpers/name","presence/viewdata/host-entity-with-presence-viewdata","msg-data/viewdata"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class o extends i.default{get title(){return this.props.formatter.formatName((0,t.getName)(this.props.profile),"full")}get subtitle(){return this.props.profile.occupation}get entityWithPresenceViewData(){const{profile:e}=this.props
return new n.default({profile:e,altText:this.title})}get editorAttribute(){return this.props.editorAttribute}}e.default=o}))
define("msg-mentions/viewdata/sdk-mention-to-invite-toast-viewdata",["exports","msg-data/utils/sdk-view-data-helpers","msg-data/viewdata","msg-shared/utils/custom-tracking"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class o extends n.default{get conversationUrn(){return this.props.conversation.entityUrn}get conversationBackendUrn(){return this.props.conversation.backendUrn}get participantTrackingUrns(){const{conversation:e}=this.props,t=(null==e?void 0:e.decoratedParticipants)??[]
return(0,i.getParticipantTrackingUrns)(t,!0)??[]}get participantPresenceStatuses(){const{conversation:e,presenceAPI:n}=this.props
return(0,t.getParticipantPresenceStatuses)(e.participants,n)}}e.default=o}))
define("msg-mentions/viewdata/sdk-mentions-picker-option-viewdata",["exports","msg-data/viewdata","global-helpers/helpers/name","presence/viewdata/sdk-entity-with-presence-viewdata"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class o extends t.default{get title(){const{formatter:e,profile:t}=this.props
return e.formatName((0,n.getName)(t),"full")}get subtitle(){const{profile:e}=this.props
return e?e.headline:void 0}get entityWithPresenceViewData(){const{profile:e}=this.props
return new i.default({participant:e,altText:this.title})}get editorAttribute(){return this.props.editorAttribute}}e.default=o}))
define("msg-mentions/viewdata/sdk-mentions-picker-viewdata",["exports","msg-data/viewdata","msg-mentions/viewdata/sdk-mentions-picker-option-viewdata","msg-mentions/viewdata/connection-mentions-picker-option-viewdata"],(function(e,t,n,i){"use strict"
Object.defineProperty(e,"__esModule",{value:!0})
e.default=void 0
class o extends t.default{get conversationParticipantMentionOptions(){const{conversationParticipantMentions:e,formatter:t}=this.props
return e.map((e=>new n.default({profile:e.mentionedMemberProfile,editorAttribute:e.editorAttribute,formatter:t})))}get connectionMentionOptions(){return this.props.connectionMentions.map((e=>new i.default({profile:e.mentionedMemberProfile,editorAttribute:e.editorAttribute,formatter:this.props.formatter})))}}e.default=o}))

//# sourceMappingURL=engine-vendor.map