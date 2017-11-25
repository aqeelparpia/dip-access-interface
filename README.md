# Access Proof of Concept

## Overview

The Access Proof of Concept (real name pending) is a Django application designed to provide access to Dissemination Information Packages (i.e., access copies of digital files stored in Archival Information Packages in CCA's Archivematica-based digital repository). The application is specifically designed around the custom DIPs generated by [name of script].

The primary application, "dips", allows users to add, organize, and interact with these DIPs and the digital files they contain, depending on user permissions.

## Data Model

The application organizes and displays information in several levels:

* **Collection**: A Collection is the highest level of organization and corresponds to an archive or other assembled collection of materials. A Collection has 0 to many Folders as children (in practice, every collection shoudl also have at least one child, but this is not enforced by the application). Collections may also have unqualified Dublin Core metadata, as well as a link to a finding aid.
* **Folder**: A Folder corresponds to an Archival Information Package (AIP) and Dissemination Information Package (DIP). A Folder has 1 to many Digital Files as children, which are auto-generated from information in the AIP METS file included as part of the DIP. Folders may also have unqualified Dublin Core metadata. The DC metadata from the most recently updated dmdSec is written into the Folder record when the METS file is uploaded (except "ispartof", which is hard-coded on creation of the Folder. This might be something to change for more generalized usage).
* **Digital File**: A Digital File corresponds to a description of an original digital file in the AIP METS file, and contains detailed metadata from an AIP METS file amdSec, including a list of PREMIS events. Digital Files should never be created manually, but only generated via parsing of the METS file when a new Folder is added.

## Uploading new DIPs

When a sufficiently privileged user creates a new Folder through the GUI interface, they need only enter the identifier, choose the Collection to which the Folder belongs, and upload a copy of the zipped digital objects and a copy of the AIP METS file. The application then uses the `parsemets.py` script to parse the METS file, automatically:

* Saving Dublin Core metadata found in the (most recently updated) dmdSec to the DIP model object for the Folder
* Generating records for Digital Files and the PREMIS events associated with each digital file and saving them to the database.

In a future version of the application, it should be possible to upload a new DIP via a (not yet existing) REST API, which will similarly populate the database from the METS file.

Once the DIP has been uploaded, the metadata for the Folder can be edited through the GUI by any user with sufficient permissions.

## Permissions

By default, the application has three levels of permissions:

* **Admin**: Admin users can add, edit, and delete Departments, Collections, and Folders and add and edit Users
* **Edit Collections and Folders**: Users in this Group can add and edit Collections and Folders
* **Public**: Users with a username/password but no additional permissions have view-only access.

## Superuser credentials (dev)

Username: admin  
Password: accesspoc

## Installation (dev)

virtualenv venv -p python3  
source venv/bin/activate  
pip install -r requirements.txt

## To do
  
* Internationalization (French/English interface)
* Extract METS file to temp dir rather than current dir
* Separate "ispartof" from parent-child relationship? Keep open use for, e.g., series?  
* Add "Edit Collections and DIPs" group to Users and Edit User pages 
* Configure storage of zip and METS files: currently, everything is being saved to a "media" directory; add NFS support(?), option for multiple storage spaces
* Delete zip & METS files when Folder/DIP is deleted
* Tie user accounts to CCA domain accounts (phase 2?)  
* REST API for uploading DIPs directly from Archivematica automation-tools (phase 2?)  
* Choose which Dublin Core elements are displayed in Collection and Folder pages (user-configurable?) 
