#############################################################################
#############################################################################
#                              ReadAuditLogs.R                              #
#                                                                           #
#  Loads a local.db file and parses the AuditLog to reconstruct the         #
#  sequence of workflow states that occurred during TULSA treatments.       # 
#                                                                           #
#  Created 2019-07-26 by Robert Staruch                                     #
#                                                                           #
#############################################################################
#############################################################################


#### CHANGE LOG #############
#' 20240610 NJS
#' Code cleanup: replaced print(paste0(...)) with cat(...) for better readability.
#' Improved assignment operator spacing.
#' Added default for yearSelection in case with one argument.
#' Enhanced comment formatting for clarity.
#' 
#' Efficient package loading: The function check_and_install ensures packages are installed and loaded in one call using sapply(), suppressing redundant messages.
#' Dynamic directory handling: Patient options and directory paths are now more organized for efficient access.
#' Optimized string and path operations: The use of grep() and logical conditions simplifies selecting directories.
#' Annotations: Clear comments added to major steps to describe what each block of code is doing.
#'Handling corner cases: Added error handling and informative messages for invalid selections.

#' 20250417 - This code is way too hard to optimize and not worth it
#' Added a line reduce the data to a csv for use outside of this R script
#' 

# List of packages to check and install
packages <- c("DBI", "RSQLite", "dplyr", "dbplyr", "ggplot2", "nls2", "openxlsx", 
              "arsenal", "stringr", "datetimeutils", "patchwork")

# Function to check and install packages
check_and_install <- function(pkg) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    install.packages(pkg, dependencies = TRUE)
  }
  suppressMessages(library(pkg, character.only = TRUE))
}

# Check and install packages in a single call (efficiently handles all dependencies)
invisible(sapply(packages, check_and_install))

# Set user and working directory dynamically
myUserName <- Sys.getenv("USERNAME")
pathtoProfoundMedical <- file.path('C:/Users', myUserName, 'Profound Medical')
setwd(file.path(pathtoProfoundMedical, 'Clinical Science Team - Genius Services', 'Timing Data', 'temp'))
cat('Working directory set to', getwd(), '\n')

# Process command line arguments (args)
args <- commandArgs(trailingOnly = TRUE)

# Define patient options
patientOptions <- c(
  '001 ALTA', '002 Turku', '004 Hopkins', '005 Sunnybrook', '006 Koln', '007 Sapporo', 
  '008 UCLA', '010 Trier', '011 Strasbourg', '012 UChicago', '013 UTSW', '016 Choice',
  '017 Busch', '018 MayoJax', '048 RadnetWH', '055 Wellspan', '063 MethSA', '064 Stanford', 
  '065 Yale', '068 HaloHMI', '074 UTMB', '075 MayoRoch', '079 Sperling', '080 MethWB',
  '087 Parkhill', '088 NIH', '089 Brigham', '091 SHO', '093 HaloRR', '094 RadnetAZ',
  '096 Indiana', '099 Medige', 'TACT', 'NewECD', '109 UCSD'
)

# If arguments are valid, select patients and year based on input or prompt user
patients <- ifelse(length(args) >= 1 && args[1] %in% patientOptions, args[1], 
                   select.list(choices = patientOptions, title = 'Select patients', graphics = TRUE))

yearOptions <- c('All', 'CurrentYear', 'PastYears', as.character(2016:2024))
yearSelection <- ifelse(length(args) >= 2 && args[2] %in% yearOptions, args[2], 
                        select.list(choices = yearOptions, title = 'Select years', graphics = TRUE))

# Display selections
cat('Patient selection:', patients, 'Years:', yearSelection, '\n\n')

# Map patient options to directories for faster access
patient_paths <- list(
  '001 ALTA' = c('//pmibu01/commercialdata$', '//pmifs03/clinicaldata$/Commercial Data'),
  '004 Hopkins' = '/Clinical Science Team - Genius Services/Timing Data/Hopkins_004',
  '005 Sunnybrook' = '/Clinical Science Team - Genius Services/Timing Data/SRI_005',
  '008 UCLA' = '/Clinical Science Team - Genius Services/Timing Data/UCLA_008',
  '013 UTSW' = '/Clinical Science Team - Genius Services/Timing Data/UTSW_013',
  '016 Choice' = '/Clinical Science Team - Genius Services/Timing Data/Choice_016',
  '017 Busch' = '/Clinical Science Team - Genius Services/Timing Data/Busch_017',
  '018 MayoJax' = '/Clinical Science Team - Genius Services/Timing Data/Mayo_018',
  '048 RadnetWH' = '/Clinical Science Team - Genius Services/Timing Data/Radnet_048',
  '063 MethSA' = '/Clinical Science Team - Genius Services/Timing Data/Methodist_063',
  '064 Stanford' = '/Clinical Science Team - Genius Services/Timing Data/Stanford_064',
  '065 Yale' = '/Clinical Science Team - Genius Services/Timing Data/Yale_065',
  '068 HaloHMI' = '/Clinical Science Team - Genius Services/Timing Data/HMI_068',
  '074 UTMB' = '/Clinical Science Team - Genius Services/Timing Data/UTMB_074',
  '075 MayoRoch' = '/Clinical Science Team - Genius Services/Timing Data/MayoRoch_075',
  '079 Sperling' = '/Clinical Science Team - Genius Services/Timing Data/Sperling_079',
  '080 MethWB' = '/Clinical Science Team - Genius Services/Timing Data/MethWB_080',
  '087 Parkhill' = '/Clinical Science Team - Genius Services/Timing Data/PerigonParkhill_087',
  '091 SHO' = '/Clinical Science Team - Genius Services/Timing Data/SHO_091',
  '093 HaloRR' = '/Clinical Science Team - Genius Services/Timing Data/HaloRR_093',
  '094 RadnetAZ' = '/Clinical Science Team - Genius Services/Timing Data/RadnetAZ_094',
  '099 Medige' = '/Clinical Science Team - Genius Services/Timing Data/Medige_099',
  '109 UCSD' = '/Clinical Science Team - Genius Services/Timing Data/UCSD_109'
)

# Retrieve relevant patient directories
if (patients %in% names(patient_paths)) {
  patientfolders <- switch(patients,
                           '001 ALTA' = c(
                             grep('/001_01', list.dirs(patient_paths[['001 ALTA']][1], recursive = FALSE), value = TRUE),
                             grep('ALTA', list.dirs(patient_paths[['001 ALTA']][2], recursive = FALSE), value = TRUE)
                           ),
                           list.dirs(file.path(pathtoProfoundMedical, patient_paths[[patients]]), recursive = FALSE))
} else if (patients == 'TACT') {
  patientfolders <- grep('Cleveland|CANCELLED', list.dirs('//pmifs03/clinicaldata$/Clinical Trial Pivotal (TACT)', recursive = FALSE), invert = TRUE, value = TRUE)
} else if (patients == 'NewECD') {
  patientfolders <- list.dirs(file.path(pathtoProfoundMedical, 'Clinical Science Team - Genius Services/Timing Data/NewECD_001'), recursive = FALSE)
} else {
  cat('!!! Invalid site. Script needs to be updated !!!\n\n')
  patientfolders <- NULL
}

# Define year selection
thisyear <- as.integer(format(Sys.Date(), "%Y"))
yearlist <- switch(yearSelection,
                   'All' = 2016:thisyear,
                   'CurrentYear' = thisyear,
                   'PastYears' = 2016:(thisyear - 1),
                   as.integer(yearSelection))
if (is.null(yearlist)) {
  cat('!!! Invalid year selection. Script needs to be updated !!!\n\n')
}

# Create temporary folder for processing logs
tempfolder <- file.path(pathtoProfoundMedical, 'Clinical Science Team - Genius Services/Timing Data/temp/.')
auditlogs <- data.frame()  # Initialize data structure for storing audit logs
TxLogsFolder <- file.path(pathtoProfoundMedical, 'Clinical Science Team - Genius Services/Timing Data/TimingLogs')

# Loop through patient data folders to process logs (logfile parsing, cleaning, and workflow reconstruction)
# Details: 
# a) Find log files
# b) Clean the data
# c) Translate log entries to workflow steps
# d) Calculate time spent in each step
# e) Special processing of setup stage
# f) Aggregate all patient logs into one structure for further analysis

#===============================================================================#
for (i in 1:length(patientfolders)) {
  print( paste0('#---  Patient ', i, ' of ', length(patientfolders), '  ---#') , quote=FALSE)
  
  ## a) FIND LOGFILE  ---------------------------------------------- ##
  
  ##    First look for an unzipped local.db file
  print( paste0('      Searching ', patientfolders[i], ' for localdb...') , quote=FALSE)
  unzipped_dbfiles = Sys.glob(file.path(patientfolders[i], "*", "_*", "local.db"))
  LDBS2<-  Sys.glob(file.path(patientfolders[i], "local2.db"))
  
  if (length(unzipped_dbfiles)==0) {
    # if db file wasn't found, try a slightly different folder structure
    unzipped_dbfiles = Sys.glob(file.path(patientfolders[i], "_*", "local.db"))
  }
  if (length(unzipped_dbfiles)==0) {
    # if db file still wasn't found, try another slightly different folder structure
    unzipped_dbfiles = Sys.glob(file.path(patientfolders[i], "local.db"))
    
  }
 
  ## If there's no unzipped logfile, it might be hidden in a zipped session. Find and unzip the audit log for this case.
  if (length(unzipped_dbfiles)==0) {
    
    ## find the zipped session file
    print( paste0('      Searching ', patientfolders[i], ' for zipped session...') , quote=FALSE)
    zipped_session = Sys.glob(file.path(patientfolders[i], "TDC Sessions", "_*.zip"))
    if (length(zipped_session)==0) {
      # try a slightly different folder structure to find zipped session
      zipped_session = Sys.glob(file.path(patientfolders[i], "_201*.zip"))
    }
    if (length(zipped_session)==0) {
      # try a slightly different folder structure to find zipped session
      zipped_session = Sys.glob(file.path(patientfolders[i], "*", "_201*.zip"))
    }
    if (length(zipped_session)==0) {
      # try a slightly different folder structure to find zipped session
      zipped_session = Sys.glob(file.path(patientfolders[i], "Session*.zip"))
    } 
    if (length(zipped_session)==0) {
      print( paste0('      ...Could not find zipped session for this patient.') , quote=FALSE)
      next
    }
    
    ## search the zipped session for the logfile.
    print( paste0('      Searching ', zipped_session[1], ' for localdb...') , quote=FALSE)
    zipped_db_names <- grep('\\local.db$', unzip(zipped_session[1], list=TRUE)$Name, ignore.case=TRUE, value=TRUE)
    if (length(zipped_db_names)==0 & length(zipped_session)>1) {
      zipped_session = zipped_session[-1]
      print( paste0('      Searching ', zipped_session[1], ' for localdb...') , quote=FALSE)
      zipped_db_names <- grep('\\local.db$', unzip(zipped_session[1], list=TRUE)$Name, ignore.case=TRUE, value=TRUE)
    }
    if (length(zipped_db_names)==0) {
      print( paste0('      ...Could not find localdb in zipped session for this patient.') , quote=FALSE)
      next
    }
    
    ## extract the logfile from the zipped session
    print( paste0('      Extracting localdb from zipped session...') , quote=FALSE)
    dbfile = unzip(zipfile=zipped_session[1], files=zipped_db_names[1], exdir=tempfolder)
    
  } else {
    
    ## unzipped logfile exists, get its filename
    file.copy(unzipped_dbfiles[1], tempfolder, overwrite=TRUE)
    dbfile = paste0(substr(tempfolder,1,nchar(tempfolder)-1),'local.db')
  }
  
  
  
  ## b) OPEN AND CLEAN DATA IN THE AUDIT LOG --------------------------------------------------## 
  print( paste0('      ...Parsing localdb.') , quote=FALSE)
  localdb <- dbConnect(RSQLite::SQLite(), dbfile)
  auditlog <- tbl(localdb,"AuditLogRecords") %>% collect()
  sessions <- tbl(localdb,"Sessions") %>% collect()
  dbDisconnect(localdb)
  
  ## FILTER THE CASES BY YEAR
  treatmentYear <- substr(auditlog$TimeStamp[1],1,4)
  if (treatmentYear %in% yearlist) {
    print( paste0('      ...Treatment year ', treatmentYear, ": included"), quote=FALSE)  
  } else {
    print( paste0('      ...Treatment year ', treatmentYear, ": excluded"), quote=FALSE)
    next  # skip further processing for this case and move on to the next one
  }
  
  
  if (!(identical(LDBS2, character(0)))){
    ## unzipped logfile exists, get its filename
    file.copy(LDBS2[1], tempfolder, overwrite=FALSE)
    dbfile2 = paste0(substr(tempfolder,1,nchar(tempfolder)-1),'local2.db')
    localdb2 <- dbConnect(RSQLite::SQLite(), dbfile2)
    auditlog2 <- tbl(localdb2,"AuditLogRecords") %>% collect()
    dbDisconnect(localdb2)
    auditlog <- rbind(auditlog, auditlog2)
    #rm(auditlog2,localdb2,dbfile2)
  }
  
  
  ## Various TDC versions had different numbers and names of logged fields.  Standardize so they can be processed together.
  
  # this doesn't look right, the length is the query so these if statements do nothing.
  if (length(names(auditlog)==42)) {
    auditlog$Velocity = NA
    auditlog$NewTemperature = NA
    auditlog$OldTemperature = NA
    auditlog$Temperature = NA
  } 
  if (length(names(auditlog)==46)) {
    auditlog$UaTemperatureDegreesCelsius = NA
    auditlog$UserEnteredTemperatureDegreesCelsius = NA
  }
  if (length(names(auditlog)==48)) {
    auditlog$UATemperatureDegreesCelsius = NA
    auditlog$FirstActiveElement = NA
  }
  if ('TreatmentId' %in% names(auditlog)) {
    names(auditlog)[names(auditlog) == "TreatmentId"] <- "SegmentId"
  }
  
  try(auditlog$SignalHelpKey<- NULL)
  try(auditlog$FirstActiveElement<- NULL)
  
  ## define standardized patient number
  auditlog$Pt   = i
  if (patients=='ALTA') {
    if (length(grep('ALTA',patientfolders[i]))>0) {
      auditlog$PtId = substring(patientfolders[i], regexpr('ALTA', patientfolders[i]))
    } else {
      auditlog$PtId = paste0('ALTA',substring(patientfolders[i], regexpr('001_01', patientfolders[i]) + 6))
    }
  } else if (patients=='TACT') {
    auditlog$PtId = substring(patientfolders[i], regexpr(' -- ', patientfolders[i]) + 4)
  } else {
    # idt = substring(patientfolders[i], regexpr(' -- ', patientfolders[i]))  ## from originalhour
    # idt = substr(idt, start = nchar(idt)-9, stop = nchar(idt))
    idt = str_sub(patientfolders[i],-10,end=-1)
    auditlog$PtId = idt
  }
  
  ## filter the log down to the relevant state transitions
  auditlog = auditlog[!(auditlog$AuditRecordBase_Type=="SignalRecord"),]
  
  
  #Extracting treatment day and row template
  # Adding the fields from the treatment log into the database
  db_template <- rbind(head(auditlog,n=1))
  db_template$Id = 1 + max(auditlog$Id)

  if (length(names(sessions))>17) {
    if (grepl('2.10', sessions$TdcVersion, fixed = TRUE)){
      Ready4Urology <- sessions$TimePatientSedatedAt
      DeviceInsertionEnds <-sessions$TimeUaInsertedAt
      UARemoved <-sessions$TimeUaRemovedAt
      PatientTransferEnds <- sessions$TimePatientTransferredAt
    }}
  TxDate = as.Date(head(auditlog,n=1)$TimeStamp)
  TxLogs = Sys.glob(paste(TxLogsFolder,'/',idt,".xlsx",sep=""))
  
  ## Search for timing logs
  if (length(TxLogs)>0){
    
    TreatmentLog = read.xlsx(TxLogs,1,startRow=2,detectDates = TRUE)
    TxVariables = TreatmentLog[,1];
    TxValues    = TreatmentLog[,2];
    Events      = TreatmentLog[,3]; #RS (was 4)
    TimeSTART   = TreatmentLog[,4]; #RS (was 5)
    TimeEND     = TreatmentLog[,5]; #RS (was 6)
    AnesthesiaStart= auditlog$TimeStamp[1];

    for (k in 1:length(Events)) {
      if(!is.na(TimeSTART[k])|!is.na(TimeEND[k])){
        if (isTRUE((Events[k]=="Anesthesia Team starts to prepapre the patient ")|(Events[k]=="Anesthesia Team starts to prepare the patient "))) {
          AnesthesiaStart = format(convertToDateTime(TimeSTART[k],origin=TxDate), "%Y-%m-%d %H:%M:%OS7") #paste(TxDate, format(TimeSTART[k], "%H:%M:%OS")) 
          db_template$AuditRecordBase_Type = 'AnesthesiaStart'
          db_template$TimeStamp            = AnesthesiaStart
          auditlog <- rbind(auditlog, db_template)
          db_template$Id = 1 + max(auditlog$Id)
        } else if (isTRUE((Events[k]=="Patient is ready for Urology team"))) {
          Ready4Urology = format(convertToDateTime(TimeEND[k],origin=TxDate), "%Y-%m-%d %H:%M:%OS7")
          #if (difftime(Ready4Urology, auditlog$TimeStamp[1])>0){
          db_template$AuditRecordBase_Type = 'Ready4Urology'
          db_template$TimeStamp            = Ready4Urology
          auditlog <- rbind(auditlog, db_template)
          db_template$Id = 1 + max(auditlog$Id)
          #}
        } else if (isTRUE(((Events[k]=="Devices Insertion")))) {
          DeviceInsertionBegins = format(convertToDateTime(TimeSTART[k],origin=TxDate), "%Y-%m-%d %H:%M:%OS7")
          DeviceInsertionEnds   = format(convertToDateTime(TimeEND[k],origin=TxDate), "%Y-%m-%d %H:%M:%OS7")
          #try(if (difftime(DeviceInsertionEnds, auditlog$TimeStamp[1])>0){
          db_template$AuditRecordBase_Type = 'DeviceInsertionEnds'
          db_template$TimeStamp            = DeviceInsertionEnds
          auditlog <- rbind(auditlog, db_template)
          db_template$Id = 1 + max(auditlog$Id)
          db_template$AuditRecordBase_Type = 'DeviceInsertionBegins'
          db_template$TimeStamp            = DeviceInsertionBegins
          auditlog <- rbind(auditlog, db_template)
          db_template$Id = 1 + max(auditlog$Id)
        } else if (isTRUE(((Events[k]=="Patient Transfer from MRI Bed to Recovery room")))) {
          PatientTransferBegins = format(convertToDateTime(TimeSTART[k],origin=TxDate), "%Y-%m-%d %H:%M:%OS7") #paste(TxDate, format(TimeSTART[k], "%H:%M:%OS"))
          PatientTransferEnds   = format(convertToDateTime(TimeEND[k],origin=TxDate), "%Y-%m-%d %H:%M:%OS7")#paste(TxDate, format(TimeEND[k], "%H:%M:%OS"))
          if  (!is.na(PatientTransferBegins)){ #(difftime(PatientTransferBegins, auditlog$TimeStamp[1])>0){
            db_template$AuditRecordBase_Type = 'PatientTransferBegins'
            db_template$TimeStamp            = PatientTransferBegins
            auditlog <- rbind(auditlog, db_template)
          }
          if  (!is.na(PatientTransferEnds)){ #(difftime(PatientTransferBegins, auditlog$TimeStamp[1])>0){
            db_template$AuditRecordBase_Type = 'PatientTransferEnds'
            db_template$TimeStamp            = PatientTransferEnds
            auditlog <- rbind(auditlog, db_template)
          }
        } else if (isTRUE(((Events[k]=="Initial Device Imaging (From first until last survey)")))) {
          InitiaImaging = format(convertToDateTime(TimeSTART[k],origin=TxDate), "%Y-%m-%d %H:%M:%OS7")
          #if (difftime(InitiaImaging, auditlog$TimeStamp[1])>0){
          db_template$AuditRecordBase_Type = 'InitialImaging'
          db_template$TimeStamp            = InitiaImaging
          auditlog <- rbind(auditlog, db_template)
          db_template$Id = 1 + max(auditlog$Id)
          #}
        } else if (isTRUE(((Events[k]=="Device Removal")))) {
          DevicesRemoval = format(convertToDateTime(TimeEND[k],origin=TxDate), "%Y-%m-%d %H:%M:%OS7")#paste(TxDate, format(TimeEND[k], "%H:%M:%OS"))
        }
      }
    }}



 if(exists("AnesthesiaStart")){try(if (difftime(AnesthesiaStart, auditlog$TimeStamp[1])>0){
   db_template$AuditRecordBase_Type = 'AnesthesiaStart'
   db_template$TimeStamp            = AnesthesiaStart
   auditlog <- rbind(auditlog, db_template)
 })}

 if(exists("DeviceInsertionBegins")){try(if (difftime(DeviceInsertionBegins, auditlog$TimeStamp[1])>0){
   db_template$AuditRecordBase_Type = 'DeviceInsertionBegins'
   db_template$TimeStamp            = DeviceInsertionBegins
   auditlog <- rbind(auditlog, db_template)
 })}

 try(if (difftime(DeviceInsertionEnds, auditlog$TimeStamp[1])>0){
   db_template$AuditRecordBase_Type = 'DeviceInsertionEnds'
   db_template$TimeStamp            = DeviceInsertionEnds
   if(idt!="055_01-014")
   auditlog <- rbind(auditlog, db_template)
 })

 try(if (difftime(PatientTransferEnds, auditlog$TimeStamp[1])>0){
   db_template$AuditRecordBase_Type = 'PatientTransferEnds'
   db_template$TimeStamp            = PatientTransferEnds
   auditlog <- rbind(auditlog, db_template)
 })


  
  ## sort by timestamp
  auditlog = auditlog[order(auditlog$TimeStamp),]
  
  ## remove Alignment entries with same timestamp as Coarse confirmation image
  ## (this is done because when we load confirmation scans in Coarse planning, TDC very briefly jumps to Alignment and back to Coarse again)
  removelist = c()
  for (r in 2:nrow(auditlog)) {
    if ((auditlog$AuditRecordBase_Type[r]=='AlignmentWorkflowRecord') & (auditlog$AuditRecordBase_Type[r-1]=='CoarseWorkflowRecord')) {
      if ( (auditlog$TimeStamp[r]==auditlog$TimeStamp[r-1])  ) {
        removelist = c(removelist,r)
      }      
    }
  }
  if (!is.null(removelist)) {
    auditlog = auditlog[-c(removelist),]
  }

  ## c) TRANSLATE LOG ENTRIES INTO WORKFLOW STEPS ------------------------------------------------- ##
  ## create the timeline in one loop
  auditlog$CurrentState = ""
  auditlog$CurrentState_start      = 0
  auditlog$CurrentState_duration   = 0
  currState = ""
  for (r in 1:nrow(auditlog)) {
    if (auditlog$AuditRecordBase_Type[r]=='SetupWorkflowRecord') {
      currState = 'TULSA QA'
    } else if (auditlog$AuditRecordBase_Type[r]=='SetupUnlockWorkflowRecord'){
      currState = 'Room ready'
	} else if ((auditlog$AuditRecordBase_Type[r]=='UATestRecord')&(length(auditlog$CurrentState[auditlog$CurrentState=='Patient positioning & induction'])==0)){
      currState = 'Room ready'	  
    } else if ((auditlog$AuditRecordBase_Type[r]=='AnesthesiaStart')|(auditlog$AuditRecordBase_Type[r]=='Ready4Urology')) {
      currState = 'Patient positioning & induction' 
    } else if ((auditlog$AuditRecordBase_Type[r]=='DeviceInsertionBegins')|(auditlog$AuditRecordBase_Type[r]=='DeviceInsertionEnds')) {
      currState = 'Device insertion' 
    } else if (auditlog$AuditRecordBase_Type[r]=='InitialImaging'){
      currState = 'Device repositioning'
    } else if (auditlog$AuditRecordBase_Type[r]=='AlignmentWorkflowRecord') {  
      currState = 'Alignment'
    } else if (auditlog$AuditRecordBase_Type[r]=='CoarseWorkflowRecord' | auditlog$AuditRecordBase_Type[r]=='CoarseUnlockWorkflowRecord') {
      currState = 'Coarse'
    } else if (auditlog$AuditRecordBase_Type[r]=='DetailedWorkflowRecord') {
      currState = 'Detailed'
    } else if (auditlog$AuditRecordBase_Type[r]=='PlanReadyWorkflowRecord' | auditlog$AuditRecordBase_Type[r]=='PlanReadyCompleteWorkflowRecord') {
      currState = 'Planning start angle'
    } else if (auditlog$AuditRecordBase_Type[r]=='DeliveryInitializingWorkflowRecord') {
      currState = 'Initialization'
    } else if (auditlog$AuditRecordBase_Type[r]=='PlanReadyUserStoppedInitializationWorkflowRecord') {
      currState = 'Planning start angle'
    } else if (grepl('DeliveryPaused',auditlog$AuditRecordBase_Type[r]) ) {
      currState = 'Paused'
    } else if (auditlog$AuditRecordBase_Type[r]=='DeliveryInterruptedWorkflowRecord'){
      currState = 'Review'  
    } else if (auditlog$AuditRecordBase_Type[r]=='DeliveryWorkflowRecord' | auditlog$AuditRecordBase_Type[r]=='DeliveryResumedWorkflowRecord') {
      currState = 'Treating'
    } else if (auditlog$AuditRecordBase_Type[r]=='ReviewWorkflowRecord') {
      currState = 'Post-treatment scans & Device removal' 
    } else if ((auditlog$AuditRecordBase_Type[r]=='DevicesRemovalStarts')|(auditlog$AuditRecordBase_Type[r]=='DevicesRemovalEnds')){
      currState = 'Post-treatment scans & Device removal'
    } else if ((auditlog$AuditRecordBase_Type[r]=='PatientTransferBegins')|(auditlog$AuditRecordBase_Type[r]=='PatientTransferEnds')) {
      currState = 'Patient recovery & transfer' 
    }

    if (currState=='Post-treatment scans & Device Removal' & ( (auditlog$AuditRecordBase_Type[r]=='MriConnectionRecord') | (auditlog$AuditRecordBase_Type[r]=='SessionEventRecord' & auditlog$EventKind[r]==1) | (auditlog$AuditRecordBase_Type[r]=='SegmentEventRecord' & auditlog$EventKind[r]==2) ) ) {
      currState = '' 
    } else if (  !is.na(auditlog$SegmentId[r]) & nchar(auditlog$SegmentId[r])>1  & (substr(auditlog$SegmentId[r],1,10) != substr(auditlog$TimeStamp[r],1,10)) ) {
      currState = '' 
    } 
    
    auditlog$CurrentState[r] = currState
    
  }


  ## remove entries before setup or after review
  auditlog = auditlog[!(auditlog$CurrentState==''),]
  
  
  ## d) CALCULATE TIME spent in each workflow step  ---------------------------------------- ##
  for (r in 1:nrow(auditlog)) {
    auditlog$CurrentState_start[r] = difftime(strptime(auditlog$TimeStamp[r],'%Y-%m-%d %H:%M:%OS'),strptime(auditlog$TimeStamp[1],'%Y-%m-%d %H:%M:%OS'),units='secs')
    if (r < nrow(auditlog)) {
      auditlog$CurrentState_duration[r] = difftime(strptime(auditlog$TimeStamp[r+1],'%Y-%m-%d %H:%M:%OS'),strptime(auditlog$TimeStamp[r],'%Y-%m-%d %H:%M:%OS'),units='secs')
    }
  }
  
  
  ## e) SPECIAL HANDLING FOR ENTRIES RELATED TO DEVICE SETUP ------------------------------ ##
  ## System prep time:  find last PS test or UA test before Alignment
  Setup     <- match('SetupWorkflowRecord',auditlog$AuditRecordBase_Type)
  Alignment <- match('AlignmentWorkflowRecord',auditlog$AuditRecordBase_Type)
  PStests   <- which(auditlog$AuditRecordBase_Type %in% 'PSTestRecord')
  UAtests   <- which(auditlog$AuditRecordBase_Type %in% 'UATestRecord')
  UAhomes   <- which(auditlog$AuditRecordBase_Type %in% 'PSHomingRecord')
  #UAhomes   <- UAhomes[2]
  LastSetuDone<- min(which(auditlog$CurrentState %in% 'Room ready')) 
  
  
  PatientTransferE <- PatientTransferE <- nrow(auditlog)-1
  try(DeviceInsertionE <- which(auditlog$AuditRecordBase_Type %in% 'DeviceInsertionEnds'))
  try(AnesthesiaStartE <-  which(auditlog$AuditRecordBase_Type %in% 'AnesthesiaStart'))
  try(InitiaImagingStart <- match('InitialImaging',auditlog$AuditRecordBase_Type))
  try(DeviceInsertionStart<-match('DeviceInsertionBegins',auditlog$AuditRecordBase_Type))
  try(UrologyS  <- which(auditlog$AuditRecordBase_Type %in% 'Ready4Urology'))
  try(Review <- which(auditlog$AuditRecordBase_Type %in% 'ReviewWorkflowRecord'))
  if (length(which(auditlog$AuditRecordBase_Type %in% 'PatientTransferEnds'))>0){
    try(PatientTransferE <- which(auditlog$AuditRecordBase_Type %in% 'PatientTransferEnds'))
  } else{
        LastReview = min(Review)
        auditlog$CurrentState[LastReview:length(auditlog$CurrentState)] <- 'NA'
  }
  
  
  if (length(Review)>1){
    for (ReviewID in Review[2:length(Review)]) {
      if (difftime(strptime(auditlog$TimeStamp[ReviewID],'%Y-%m-%d %H:%M:%OS'),strptime(auditlog$TimeStamp[Review[1]],'%Y-%m-%d %H:%M:%OS'),units='min')>30){
        auditlog$CurrentState[ReviewID] = 'NA'
      }
    }
  }


  LastReview = max(Review[Review>PatientTransferE])
  auditlog$CurrentState[PatientTransferE:length(auditlog$CurrentState)] = 'NA'
  #   }else{
  #    LastReview = min(Review)
  #    auditlog$CurrentState[LastReview:length(auditlog$CurrentState)] <- 'NA'
  #   }


  LastPStest = 0
  if ( length(PStests)>0 & (PStests[1]<Alignment) ) {
    LastPStest = max(PStests[PStests<Alignment])
  } 
  if ( length(UAtests)>0 & (UAtests[1]<Alignment) ) {
    LastPStest = max(LastPStest,max(UAtests[UAtests<Alignment]))
  } 
  if (LastPStest<=1) { #old TDC version
    LastPStest = ifelse( length(UAhomes)>1, UAhomes[1], Setup )
  }
  
  # Patient prep:  from PS test to first UA homing
  FirstUAHoming <- min(UAhomes[UAhomes>LastPStest])
  LastUAHoming  <- max(UAhomes[UAhomes<Alignment])
  
  try(if(length(DeviceInsertionE)>0 & length(InitiaImagingStart)>0 & !is.na(InitiaImagingStart)){
    auditlog$CurrentState[DeviceInsertionE:InitiaImagingStart] = 'Device insertion'}) 
  # 
  #  try(if (length(UrologyS)>0 & length(DeviceInsertionE)==0){
  #    auditlog$CurrentState[UrologyS:LastUAHoming] = 'TULSA QA'})


  if (length(UAhomes>0)) {
    # Initial imaging:  from UA homing to Alignment
    if (length(InitiaImagingStart)=='NA' | is.na(InitiaImagingStart) ){
      auditlog$CurrentState[(LastUAHoming):(Alignment-1)] = 'Device repositioning'
      auditlog$CurrentState_start = auditlog$CurrentState_start - auditlog$CurrentState_start[LastUAHoming ]
    } else{
      auditlog$CurrentState[(InitiaImagingStart):(Alignment-1)] = 'Device repositioning'
      # adjust to make initial imaging time 0
      auditlog$CurrentState_start = auditlog$CurrentState_start - auditlog$CurrentState_start[InitiaImagingStart]
      # adjust to make device insertion time 0
      #auditlog$CurrentState_start = auditlog$CurrentState_start - auditlog$CurrentState_start[DeviceInsertionStart]
      }

  } else {
    # UA never homed?  just start with alignment
    auditlog$CurrentState_start = auditlog$CurrentState_start - auditlog$CurrentState_start[Alignment]
  }


  ## f) ADD TO BIG LIST OF ALL LOG FILES ----------------------------------------------- ##
  
  ## sort the workflow stages
  auditlog$CurrentState <- factor(auditlog$CurrentState, c('TULSA QA','Room ready','Patient positioning & induction', 'Device insertion','Device repositioning', 'Alignment', 'Coarse', 'Detailed', 'Planning start angle', 'Initialization', 'Treating', 'Paused','Review','Post-treatment scans & Device removal','Patient recovery & transfer','NA') )
  
  # append to list of auditlogs
  if (nrow(auditlogs)==0) {
    auditlogs = auditlog  
  } else {
    auditlogs = rbind(auditlogs,auditlog)
  }
  
  try(rm(AnesthesiaStart,AnesthesiaStartE,Alignment,DeviceInsertionBegins,DeviceInsertionE,DeviceInsertionEnds,FirstUAHoming,InitiaImaging,InitiaImagingStart,InitialImagingEnd,LastPStest,LastReview,LastSetuDone,LastUAHoming,PatientTransferBegins,PatientTransferE,PatientTransferEnds,Ready4Urology,Review,Setup,UrologyS,UAtests))
}

write.csv(auditlogs, paste0(tempfolder,'auditlogs_',patients,'.csv'))

library(data.table)

# Ensure correct timestamp formatting before saving
auditlogs$TimeStamp <- as.character(auditlogs$TimeStamp)

# Save without row numbers
fwrite(auditlogs, file.path(tempfolder, paste0('auditlogs_NS_', patients, '.csv')), row.names = FALSE)


print( paste0('#---  Auditlogs Saved.  ---#') , quote=FALSE)
print( paste0(' ') , quote=FALSE)
print( paste0(' ') , quote=FALSE)

## --------------------------------------------------------------------------------------- ##
## --------------------------------------------------------------------------------------- ##
print( paste0(' ') , quote=FALSE)
print( paste0('#---  Plotting treatment timeline  ---#') , quote=FALSE)
## --------------------------------------------------------------------------------------- ##
## --------------------------------------------------------------------------------------- ##
if (!exists('auditlogs')) {
  auditlogs = read.csv(paste0(tempfolder,'auditlogs_',patients,'.csv'))
}

earliest = min(auditlogs$CurrentState_start[auditlogs$CurrentState!="NA"], na.rm=TRUE)
latest = max(auditlogs$CurrentState_start[auditlogs$CurrentState!="NA"] + auditlogs$CurrentState_duration[auditlogs$CurrentState!="NA"], na.rm=TRUE)

workflowcolors <- c("TULSA QA" = "gray85",'Room ready'='gray70','Patient positioning & induction'="gray55",'Device insertion'='darkseagreen3',"Device repositioning" = "darkseagreen4", "Alignment" = "lightblue", "Coarse" = "royalblue", "Detailed" = "royalblue4", "Planning start angle" = "navy", "Initialization" = "lightgoldenrod", "Treating"="goldenrod", "Paused"="darkgoldenrod", 'Review'="darkgoldenrod4", "Post-treatment scans & Device removal"="darkseagreen1",'Patient recovery & transfer'='thistle4','NA'='white')
chron <- ggplot(auditlogs, aes(xmin=CurrentState_start, 
                               xmax=CurrentState_start+CurrentState_duration,
                               ymin=Pt-0.5,
                               ymax=Pt+0.5),na.value="white") + 
  geom_rect(aes(fill=CurrentState)) +
  scale_color_manual(values=workflowcolors, aesthetics = c("colour", "fill")) +
  #scale_x_continuous(labels=function(x)x/3600, breaks=seq(-2*3600,6*3600,by=3600), limits=c(-2*3600,6*3600), expand=c(0,0) ) +
  scale_x_continuous(labels=function(x)x/3600, breaks=seq(-6*3600,12*3600,by=3600), limits=c(earliest,latest), expand=c(0,0) ) + 
  scale_y_reverse(lim=c(length(patientfolders)+0.5,0.5), breaks=auditlogs$Pt, labels=str_sub(auditlogs$PtId,-3,end=-1), expand=c(0,0)) + 
  geom_vline(xintercept = 0) +
  xlab('Hours') +
  ylab('Patient') +
  theme_classic() +
  theme(
    legend.background = element_rect(color = "transparent",fill = "transparent"), # get rid of legend bg
    legend.title=element_blank(), 
    #legend.position=c(-.20,.34),
    legend.position="bottom",
    text = element_text(size=11),
    strip.background = element_blank()
  )
suppressWarnings( print(chron), classes="warning")
suppressWarnings( ggsave(paste0("TULSA_timing_normalized_",patients,".png"), chron, width = 6, height = max(2+length(patientfolders)*0.125,3), units = 'in', dpi = 300, limitsize = FALSE), classes="warning")







## --------------------------------------------------------------------------------------- ##
## --------------------------------------------------------------------------------------- ##
print( paste0(' ') , quote=FALSE)
print( paste0('#---  Plotting treatment timeline (original hour) ---#') , quote=FALSE)
## --------------------------------------------------------------------------------------- ##
## --------------------------------------------------------------------------------------- ##


# From OriginalHour, needed for the other plot. 
# Note that this strips the date information from auditlogs, 
# so don't save auditlogs after this block.
TxDate = "2020-01-01"
auditlogs$TimeStampOH <- auditlogs$TimeStamp
for (r in 1:length(auditlogs$TimeStampOH)) {
  temp=strsplit(auditlogs$TimeStampOH[r]," ") # split the string into [1] date and [2] time
  time <- unlist(temp)[2]  # take just the time
  auditlogs$TimeStampOH[r] <- paste(as.POSIXct(paste(TxDate,time )))  # use standard date and actual time
}

# plotting code from originalHour: 
if (!exists('auditlogs')) {
  auditlogs = read.csv(paste0(tempfolder,'auditlogs_',patients,'.csv'))
}

#lims <- as.POSIXct(strptime(c("2020-01-01 05:30", "2020-01-01 22:00"), format = "%Y-%m-%d %H:%M"))
lims <- as.POSIXct(strptime(c( min(auditlogs$TimeStampOH[auditlogs$CurrentState!="NA"],na.rm=TRUE), max(auditlogs$TimeStampOH[auditlogs$CurrentState!="NA"],na.rm=TRUE) ), format = "%Y-%m-%d %H:%M"))

workflowcolors <- c("TULSA QA" = "gray85",'Room ready'='gray70','Patient positioning & induction'="gray55",'Device insertion'='darkseagreen3',"Device repositioning" = "darkseagreen4", "Alignment" = "lightblue", "Coarse" = "royalblue", "Detailed" = "royalblue4", "Planning start angle" = "navy", "Initialization" = "lightgoldenrod", "Treating"="goldenrod", "Paused"="darkgoldenrod", 'Review'="darkgoldenrod4", "Post-treatment scans & Device removal"="darkseagreen1",'Patient recovery & transfer'='thistle4','NA'='white')
chron2 <- ggplot(auditlogs, aes(xmin=as.POSIXct(TimeStampOH,origin=TxDate), 
                                xmax=as.POSIXct(TimeStampOH,origin=TxDate)+
                                  CurrentState_duration,ymin=Pt-0.5,ymax=Pt+0.5
                                )
                 ) + 
  geom_rect(aes(fill=CurrentState)) +
  scale_color_manual(values=workflowcolors, aesthetics = c("colour", "fill")) +
  scale_y_reverse(lim=c(length(patientfolders)+0.5,0.5), breaks=auditlogs$Pt, labels=str_sub(auditlogs$PtId,-3,end=-1), expand=c(0,0)) + 
  geom_vline(xintercept = 0) +
  scale_x_datetime(breaks = "1 hour",date_labels = "%H:%M",limits = lims)+
  xlab('Hours') +
  ylab('Patient') +
  theme_classic() +
  theme(
    legend.title=element_blank(), 
    text = element_text(size=11),
    strip.background = element_blank()
  )+ theme(panel.grid.major.x = element_line(colour = "gray87"))
suppressWarnings( print(chron2), classes="warning")
suppressWarnings( ggsave(paste0("TULSA_timing_originalHour_",patients,".png"), chron2, width = 7, height = max(2.5+length(patientfolders)*0.125,3), units = 'in', dpi = 300, limitsize = FALSE), classes="warning")




## --------------------------------------------------------------------------------------- ##
## --------------------------------------------------------------------------------------- ##
print( paste0(' ') , quote=FALSE)
print( paste0('#---  Preparing and saving timing summary ---#') , quote=FALSE)
## --------------------------------------------------------------------------------------- ##
## --------------------------------------------------------------------------------------- ##
if (!exists('auditlogs')) {
  auditlogs = read.csv(paste0(tempfolder,'auditlogs_',patients,'.csv'))
}

## record the start and end times for each patient
auditlogs$starttime = NA
auditlogs$endtime = NA
pts = unique(auditlogs$PtId)
for ( pti in 1:length(pts) ) {
  timestamps = auditlogs$TimeStamp[auditlogs$PtId==pts[pti]] # gets list of all timestamps for this patient
  auditlogs$starttime[ auditlogs$PtId==pts[pti]  ] = as.character(timestamps[1])  #first
  auditlogs$endtime[ auditlogs$PtId==pts[pti] ]   = as.character(timestamps[ length(timestamps) ])  #last, note this doesn't exclude timestamps with no state
}
auditlogs[auditlogs == 0] <- NA



## gather the data and produce a timing summary file.  Maybe needs work.

# Add column with the original order
order <- seq(1:length(auditlogs$Pt))
auditlogs$order <- order

# Aggregate each type of CurrentState by patient. starttime/endtime are for the whole case, they will make sense after reshape.
timing <- aggregate(. ~ Pt + PtId + CurrentState + starttime + endtime, auditlogs[,c('Pt','PtId','CurrentState','CurrentState_duration','starttime','endtime')], sum)
timing$CurrentState_duration<-timing$CurrentState_duration/60
timing_summary <- reshape(timing, idvar=c('PtId','Pt','starttime','endtime'), timevar = 'CurrentState', direction='wide')

if(is.null(timing_summary$`CurrentState_duration.Review`)){timing_summary$`CurrentState_duration.Review`=0}

timing_summary$MRITotal <- rowSums(timing_summary[,c('CurrentState_duration.Patient positioning & induction','CurrentState_duration.Device insertion','CurrentState_duration.Device repositioning','CurrentState_duration.Alignment','CurrentState_duration.Coarse','CurrentState_duration.Detailed','CurrentState_duration.Planning start angle','CurrentState_duration.Initialization',"CurrentState_duration.Paused",'CurrentState_duration.Review',"CurrentState_duration.Treating",'CurrentState_duration.Post-treatment scans & Device removal','CurrentState_duration.Patient recovery & transfer')], na.rm=TRUE)
timing_summary$ProcedureTotal <- rowSums(timing_summary[,c('CurrentState_duration.TULSA QA','CurrentState_duration.Room ready','CurrentState_duration.Patient positioning & induction','CurrentState_duration.Device insertion','CurrentState_duration.Device repositioning','CurrentState_duration.Alignment','CurrentState_duration.Coarse','CurrentState_duration.Detailed','CurrentState_duration.Planning start angle','CurrentState_duration.Initialization',"CurrentState_duration.Treating","CurrentState_duration.Paused",'CurrentState_duration.Review','CurrentState_duration.Post-treatment scans & Device removal','CurrentState_duration.Patient recovery & transfer')], na.rm=TRUE)

# Create useful groupings of CurrentState durations.  THIS PART NEEDS TO ALIGN WITH WHAT WE WANT DOCTORS TO SEE
#timing_summary$Planning <- rowSums(timing_summary[,c("CurrentState_duration.Alignment", "CurrentState_duration.Coarse","CurrentState_duration.Detailed","CurrentState_duration.Planning start angle")], na.rm=TRUE)
#timing_summary$AnesthesiaTotal <- rowSums(timing_summary[,c('CurrentState_duration.Anesthesia Begins','ProcedureTotal',"CurrentState_duration.Patient Transfer")], na.rm=TRUE)

#timing_summary$code5X008_pre   <- rowSums(timing_summary[,c('CurrentState_duration.Patient positioning & induction')], na.rm=TRUE)
timing_summary$code5X008_intra <- rowSums(timing_summary[,c('CurrentState_duration.Device insertion','CurrentState_duration.Device repositioning','CurrentState_duration.Alignment','CurrentState_duration.Coarse','CurrentState_duration.Detailed','CurrentState_duration.Planning start angle','CurrentState_duration.Initialization',"CurrentState_duration.Treating","CurrentState_duration.Paused",'CurrentState_duration.Review','CurrentState_duration.Post-treatment scans & Device removal')], na.rm=TRUE)
timing_summary$code5X006_intra <- rowSums(timing_summary[,c('CurrentState_duration.Device insertion','CurrentState_duration.Device repositioning','CurrentState_duration.Post-treatment scans & Device removal')], na.rm=TRUE)
timing_summary$code5X007_intra <- rowSums(timing_summary[,c('CurrentState_duration.Device repositioning','CurrentState_duration.Alignment','CurrentState_duration.Coarse','CurrentState_duration.Detailed','CurrentState_duration.Planning start angle','CurrentState_duration.Initialization',"CurrentState_duration.Treating","CurrentState_duration.Paused",'CurrentState_duration.Review','CurrentState_duration.Post-treatment scans & Device removal')], na.rm=TRUE)
#timing_summary$code5X008_pre_intra        <- rowSums(timing_summary[,c('CurrentState_duration.Patient positioning & induction','CurrentState_duration.Device insertion','CurrentState_duration.Device repositioning','CurrentState_duration.Alignment','CurrentState_duration.Coarse','CurrentState_duration.Detailed','CurrentState_duration.Planning start angle','CurrentState_duration.Initialization',"CurrentState_duration.Treating","CurrentState_duration.Paused",'CurrentState_duration.Review','CurrentState_duration.Post-treatment scans & Device removal')], na.rm=TRUE)


#timing_summary$Anesthesia <- timing_summary$'CurrentState_duration.Anesthesia Begins'
#timing_summary$DeviceInsertion <- timing_summary$'CurrentState_duration.Device insertion'
#timing_summary$InitialImaging <- timing_summary$'CurrentState_duration.Initial Imaging'
#timing_summary$MRI <- rowSums(timing_summary[,c("CurrentState_duration.Initial Imaging","Planning","CurrentState_duration.Treatment Initialization","CurrentState_duration.Treating","CurrentState_duration.Paused","CurrentState_duration.Interrupted","CurrentState_duration.Review")], na.rm=TRUE)
#timing_summary$Ablation <- timing_summary$CurrentState_duration.Treating
#timing_summary$PatientTransfer <- timing_summary$'CurrentState_duration.Patient Transfer'
#timing_summary$Coarse <- timing_summary$'CurrentState_duration.Coarse'
#timing_summary$Detailed <- timing_summary$'CurrentState_duration.Detailed'
#timing_summary$Paused <- timing_summary$'CurrentState_duration.Paused'

write.csv(timing_summary, paste0(tempfolder,'timing_summary_rs_',patients,'.csv'))

print( paste0(' ') , quote=FALSE)
print( paste0('#---  Timing summary saved. ---#') , quote=FALSE)

