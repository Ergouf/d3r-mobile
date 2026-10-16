/* Recovered from the preserved host ELF; not guessed command names. */
/* Source SHA-256: 3f9ae6b2275c58b2ed6313cad3b9f96d2c72532337d9ff26f451c0b820482149 */
#ifndef D3_SERVICE_NAMES_H
#define D3_SERVICE_NAMES_H
#include <stddef.h>
#include <stdint.h>

enum {
    D3_IF_NONE = 0,
    D3_IF_SM = 1,
    D3_IF_APPLET_OE = 2,
    D3_IF_APPLICATION_PROXY = 3,
    D3_IF_APPLICATION_FUNCTIONS = 4,
    D3_IF_DEBUG_FUNCTIONS = 5,
    D3_IF_PCTL = 6,
    D3_IF_AOC = 7,
    D3_IF_FSP_SRV = 8,
    D3_IF_LM = 9,
    D3_IF_LOGGER = 10,
    D3_IF_APM = 11,
    D3_IF_COMMON_STATE_GETTER = 12,
    D3_IF_SELF_CONTROLLER = 13,
    D3_IF_WINDOW_CONTROLLER = 14,
    D3_IF_AUDIO_CONTROLLER = 15,
    D3_IF_DISPLAY_CONTROLLER = 16,
    D3_IF_PROCESS_WINDING_CONTROLLER = 17,
    D3_IF_LIBRARY_APPLET_CREATOR = 18,
    D3_IF_LIBRARY_APPLET_ACCESSOR = 19,
    D3_IF_LIBRARY_APPLET_SELF_ACCESSOR = 20,
    D3_IF_STORAGE = 21,
    D3_IF_TIME = 22,
    D3_IF_TIME_ZONE = 23,
};

typedef struct { uint32_t command; const char *name; } d3_command_name;
typedef struct { int iface; const char *name; const d3_command_name *commands; uint32_t count; } d3_command_set;

static const d3_command_name d3_commands_IApplicationProxyService[] = {
    {0, NULL},
};

static const d3_command_name d3_commands_IApplicationProxy[] = {
    {0, NULL},
};

static const d3_command_name d3_commands_IApplicationFunctions[] = {
    {10u, "CreateApplicationAndPushAndRequestToStart"},
    {11u, "CreateApplicationAndPushAndRequestToStartForQuest"},
    {12u, "CreateApplicationAndRequestToStart"},
    {13u, "CreateApplicationAndRequestToStartForQuest"},
    {14u, "CreateApplicationWithAttributeAndPushAndRequestToStartForQuest"},
    {15u, "CreateApplicationWithAttributeAndRequestToStartForQuest"},
    {20u, "EnsureSaveData"},
    {21u, "GetDesiredLanguage"},
    {22u, "SetTerminateResult"},
    {23u, "GetDisplayVersion"},
    {24u, "GetLaunchStorageInfoForDebug"},
    {25u, "ExtendSaveData"},
    {26u, "GetSaveDataSize"},
    {27u, "CreateCacheStorage"},
    {30u, "BeginBlockingHomeButtonShortAndLongPressed"},
    {31u, "EndBlockingHomeButtonShortAndLongPressed"},
    {32u, "BeginBlockingHomeButton"},
    {33u, "EndBlockingHomeButton"},
    {40u, "NotifyRunning"},
    {50u, "GetPseudoDeviceId"},
    {60u, "SetMediaPlaybackStateForApplication"},
    {65u, "IsGamePlayRecordingSupported"},
    {66u, "InitializeGamePlayRecording"},
    {67u, "SetGamePlayRecordingState"},
    {68u, "RequestFlushGamePlayingMovieForDebug"},
    {70u, "RequestToShutdown"},
    {71u, "RequestToReboot"},
    {80u, "ExitAndGoBackQuestMenu"},
    {90u, "EnableApplicationCrashReport"},
    {100u, "InitializeApplicationCopyrightFrameBuffer"},
    {102u, "SetApplicationCopyrightVisibility"},
    {110u, "QueryApplicationPlayStatistics"},
    {111u, "QueryApplicationPlayStatisticsByUid"},
    {120u, "ExecuteProgram"},
    {121u, "ClearUserChannel"},
    {122u, "UnpopToUserChannel"},
    {123u, "GetPreviousProgramIndex"},
    {124u, "EnableApplicationAllThreadDumpOnCrash"},
    {130u, "GetGpuErrorDetectedSystemEvent"},
    {500u, "StartContinuousRecordingFlushForDebug"},
    {1001u, "PrepareForJit"},
};

static const d3_command_name d3_commands_ICommonStateGetter[] = {
    {1u, "ReceiveMessage"},
    {2u, "GetThisAppletKind"},
    {3u, "AllowToEnterSleep"},
    {4u, "DisallowToEnterSleep"},
    {5u, "GetOperationMode"},
    {6u, "GetPerformanceMode"},
    {7u, "GetCradleStatus"},
    {8u, "GetBootMode"},
    {9u, "GetCurrentFocusState"},
    {10u, "RequestToAcquireSleepLock"},
    {11u, "ReleaseSleepLock"},
    {12u, "ReleaseSleepLockTransiently"},
    {13u, "GetAcquiredSleepLockEvent"},
    {20u, "PushToGeneralChannel"},
    {40u, "GetCradleFwVersion"},
    {50u, "IsVrModeEnabled"},
    {51u, "SetVrModeEnabled"},
    {52u, "SetLcdBacklighOffEnabled"},
    {53u, "BeginVrModeEx"},
    {54u, "EndVrModeEx"},
    {55u, "IsInControllerFirmwareUpdateSection"},
    {60u, "GetDefaultDisplayResolution"},
    {61u, "GetDefaultDisplayResolutionChangeEvent"},
    {62u, "GetHdcpAuthenticationState"},
    {63u, "GetHdcpAuthenticationStateChangeEvent"},
    {64u, "SetTvPowerStateMatchingMode"},
    {65u, "GetApplicationIdByContentActionName"},
    {66u, "SetCpuBoostMode"},
    {80u, "PerformSystemButtonPressingIfInFocus"},
    {90u, "SetPerformanceConfigurationChangedNotification"},
    {91u, "GetCurrentPerformanceConfiguration"},
    {200u, "GetOperationModeSystemInfo"},
};

static const d3_command_name d3_commands_ISelfController[] = {
    {1u, "LockExit"},
    {2u, "UnlockExit"},
    {3u, "EnterFatalSection"},
    {4u, "LeaveFatalSection"},
    {9u, "GetLibraryAppletLaunchableEvent"},
    {10u, "SetScreenShotPermission"},
    {11u, "SetOperationModeChangedNotification"},
    {12u, "SetPerformanceModeChangedNotification"},
    {13u, "SetFocusHandlingMode"},
    {14u, "SetRestartMessageEnabled"},
    {15u, "SetScreenShotAppletIdentityInfo"},
    {16u, "SetOutOfFocusSuspendingEnabled"},
    {17u, "SetControllerFirmwareUpdateSection"},
    {18u, "SetRequiresCaptureButtonShortPressedMessage"},
    {19u, "SetAlbumImageOrientation"},
    {20u, "SetDesirableKeyboardLayout"},
    {40u, "CreateManagedDisplayLayer"},
    {41u, "IsSystemBufferSharingEnabled"},
    {42u, "GetSystemSharedLayerHandle"},
    {43u, "GetSystemSharedBufferHandle"},
    {50u, "SetHandlesRequestToDisplay"},
    {51u, "ApproveToDisplay"},
    {60u, "OverrideAutoSleepTimeAndDimmingTime"},
    {61u, "SetMediaPlaybackState"},
    {62u, "SetIdleTimeDetectionExtension"},
    {63u, "GetIdleTimeDetectionExtension"},
    {64u, "SetInputDetectionSourceSet"},
    {65u, "ReportUserIsActive"},
    {66u, "GetCurrentIlluminance"},
    {67u, "IsIlluminanceAvailable"},
    {68u, "SetAutoSleepDisabled"},
    {69u, "IsAutoSleepDisabled"},
    {70u, "ReportMultimediaError"},
    {71u, "GetCurrentIlluminanceEx"},
    {80u, "SetWirelessPriorityMode"},
    {90u, "GetAccumulatedSuspendedTickValue"},
    {91u, "GetAccumulatedSuspendedTickChangedEvent"},
    {100u, "SetAlbumImageTakenNotificationEnabled"},
    {110u, "SetApplicationAlbumUserData"},
};

static const d3_command_name d3_commands_IWindowController[] = {
    {1u, "GetAppletResourceUserId"},
    {2u, "GetAppletResourceUserIdOfCallerApplet"},
    {10u, "AcquireForegroundRights"},
    {11u, "ReleaseForegroundRights"},
    {12u, "RejectToChangeIntoBackground"},
    {20u, "SetAppletWindowVisibility"},
    {21u, "SetAppletGpuTimeSlice"},
};

static const d3_command_name d3_commands_IAudioController[] = {
    {1u, "GetMainAppletExpectedMasterVolume"},
    {2u, "GetLibraryAppletExpectedMasterVolume"},
    {3u, "ChangeMainAppletMasterVolume"},
    {4u, "SetTransparentVolumeRate"},
};

static const d3_command_name d3_commands_IDisplayController[] = {
    {1u, "UpdateLastForegroundCaptureImage"},
    {2u, "GetLastApplicationCaptureImage"},
    {3u, "GetCallerAppletCaptureImage"},
    {4u, "UpdateCallerAppletCaptureImage"},
    {5u, "GetLastForegroundCaptureImageEx"},
    {6u, "GetLastApplicationCaptureImageEx"},
    {7u, "GetCallerAppletCaptureImageEx"},
    {8u, "TakeScreenShotOfOwnLayer"},
    {9u, "CopyBetweenCaptureBuffers"},
    {10u, "AcquireLastApplicationCaptureBuffer"},
    {11u, "ReleaseLastApplicationCaptureBuffer"},
    {12u, "AcquireLastForegroundCaptureBuffer"},
    {13u, "ReleaseLastForegroundCaptureBuffer"},
    {14u, "AcquireCallerAppletCaptureBuffer"},
    {15u, "ReleaseCallerAppletCaptureBuffer"},
    {16u, "AcquireLastApplicationCaptureBufferEx"},
    {17u, "AcquireLastForegroundCaptureBufferEx"},
    {18u, "AcquireCallerAppletCaptureBufferEx"},
    {20u, "ClearCaptureBuffer"},
    {21u, "ClearAppletTransitionBuffer"},
    {22u, "AcquireLastApplicationCaptureSharedBuffer"},
    {23u, "ReleaseLastApplicationCaptureSharedBuffer"},
    {24u, "AcquireLastForegroundCaptureSharedBuffer"},
    {25u, "ReleaseLastForegroundCaptureSharedBuffer"},
    {26u, "AcquireCallerAppletCaptureSharedBuffer"},
    {27u, "ReleaseCallerAppletCaptureSharedBuffer"},
    {28u, "TakeScreenShotOfOwnLayerEx"},
};

static const d3_command_name d3_commands_IProcessWindingController[] = {
    {21u, "PushContext"},
    {23u, "CancelWindingReservation"},
    {30u, "WindAndDoReserved"},
    {40u, "ReserveToStartAndWaitAndUnwindThis"},
    {41u, "ReserveToStartAndWait"},
};

static const d3_command_name d3_commands_ILibraryAppletCreator[] = {
    {1u, "TerminateAllLibraryApplets"},
    {2u, "AreAnyLibraryAppletsLeft"},
};

static const d3_command_name d3_commands_ILibraryAppletAccessor[] = {
    {50u, "SetOutOfFocusApplicationSuspendingEnabled"},
    {100u, "PushInData"},
    {102u, "PushExtraStorage"},
    {103u, "PushInteractiveInData"},
    {105u, "GetPopOutDataEvent"},
    {106u, "GetPopInteractiveOutDataEvent"},
    {110u, "NeedsToExitProcess"},
    {120u, "GetLibraryAppletInfo"},
    {150u, "RequestForAppletToGetForeground"},
    {160u, "GetIndirectLayerConsumerHandle"},
};

static const d3_command_name d3_commands_ILibraryAppletSelfAccessor[] = {
    {1u, "PushOutData"},
    {3u, "PushInteractiveOutData"},
    {5u, "GetPopInDataEvent"},
    {6u, "GetPopInteractiveInDataEvent"},
    {10u, "ExitProcessAndReturn"},
    {11u, "GetLibraryAppletInfo"},
    {12u, "GetMainAppletIdentityInfo"},
    {13u, "CanUseApplicationCore"},
    {14u, "GetCallerAppletIdentityInfo"},
    {15u, "GetMainAppletApplicationControlProperty"},
    {16u, "GetMainAppletStorageId"},
    {17u, "GetCallerAppletIdentityInfoStack"},
    {18u, "GetNextReturnDestinationAppletIdentityInfo"},
    {19u, "GetDesirableKeyboardLayout"},
    {25u, "GetPopExtraStorageEvent"},
    {30u, "UnpopInData"},
    {31u, "UnpopExtraStorage"},
    {40u, "GetIndirectLayerProducerHandle"},
    {50u, "ReportVisibleError"},
    {60u, "GetMainAppletApplicationDesiredLanguage"},
    {70u, "GetCurrentApplicationId"},
    {80u, "RequestExitToSelf"},
    {90u, "CreateApplicationAndPushAndRequestToLaunch"},
    {101u, "ReserveResourceForMovieOperation"},
    {102u, "UnreserveResourceForMovieOperation"},
    {110u, "GetMainAppletAvailableUsers"},
    {512u, "ReportVisibleErrorWithErrorContext"},
};

static const d3_command_name d3_commands_IStorage[] = {
    {0, NULL},
};

static const d3_command_name d3_commands_ITimeService[] = {
    {3u, "GetTimeZoneService"},
};

static const d3_command_name d3_commands_ITimeZoneService[] = {
    {0u, "GetDeviceLocationName"},
};

static const d3_command_set d3_command_sets[] = {
    {2, "IApplicationProxyService", d3_commands_IApplicationProxyService, 0},
    {3, "IApplicationProxy", d3_commands_IApplicationProxy, 0},
    {4, "IApplicationFunctions", d3_commands_IApplicationFunctions, 41},
    {12, "ICommonStateGetter", d3_commands_ICommonStateGetter, 32},
    {13, "ISelfController", d3_commands_ISelfController, 39},
    {14, "IWindowController", d3_commands_IWindowController, 7},
    {15, "IAudioController", d3_commands_IAudioController, 4},
    {16, "IDisplayController", d3_commands_IDisplayController, 27},
    {17, "IProcessWindingController", d3_commands_IProcessWindingController, 5},
    {18, "ILibraryAppletCreator", d3_commands_ILibraryAppletCreator, 2},
    {19, "ILibraryAppletAccessor", d3_commands_ILibraryAppletAccessor, 10},
    {20, "ILibraryAppletSelfAccessor", d3_commands_ILibraryAppletSelfAccessor, 27},
    {21, "IStorage", d3_commands_IStorage, 0},
    {D3_IF_TIME, "ITimeService", d3_commands_ITimeService, 1},
    {D3_IF_TIME_ZONE, "ITimeZoneService", d3_commands_ITimeZoneService, 1},
};
#define D3_COMMAND_SET_COUNT (sizeof d3_command_sets / sizeof d3_command_sets[0])
#endif
